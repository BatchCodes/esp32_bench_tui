#include "bench_radio/bench_radio.hpp"

#include <algorithm>
#include <atomic>
#include <cstdio>
#include <cstring>

#include "bench_protocol/bench_protocol.hpp"
#include "esp_check.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

#if CONFIG_BENCH_RADIO_BLE
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#endif

namespace bench_radio {

namespace {

constexpr const char* kTag = "radio";
constexpr size_t kMaxAps = 24;
constexpr size_t kChannels = 13;
constexpr uint32_t kHopPeriodMs = 100;
constexpr uint32_t kChannelReportMs = kHopPeriodMs * kChannels;
constexpr uint32_t kStatusPeriodMs = 1000;
constexpr size_t kBleTableSize = 64;
constexpr size_t kMaxBleReport = 32;
constexpr uint32_t kBleReportMs = 1000;
constexpr uint32_t kBleForgetMs = 30000;

enum class StaState { Off, Idle, Connecting, Connected, Failed };

Emit emit_line = nullptr;
SemaphoreHandle_t lock = nullptr;

uint32_t now_ms() {
    return static_cast<uint32_t>(esp_timer_get_time() / 1000);
}

class Locked {
public:
    Locked() { xSemaphoreTake(lock, portMAX_DELAY); }
    ~Locked() { xSemaphoreGive(lock); }
    Locked(const Locked&) = delete;
    Locked& operator=(const Locked&) = delete;
};

bool nvs_ready = false;

esp_err_t ensure_nvs() {
    if (nvs_ready) {
        return ESP_OK;
    }
    esp_err_t result = nvs_flash_init();
    if (result == ESP_ERR_NVS_NO_FREE_PAGES || result == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_RETURN_ON_ERROR(nvs_flash_erase(), kTag, "NVS erase failed");
        result = nvs_flash_init();
    }
    ESP_RETURN_ON_ERROR(result, kTag, "NVS init failed");
    nvs_ready = true;
    return ESP_OK;
}

#if CONFIG_BENCH_RADIO_WIFI

bool wifi_started = false;
uint32_t scan_period_ms = 0;
uint32_t next_scan_ms = 0;
std::atomic<bool> scan_running{false};
std::atomic<bool> scan_done{false};
bool sniffer_on = false;
int sniff_channel = 1;
uint32_t next_hop_ms = 0;
uint32_t next_channels_ms = 0;
std::atomic<uint32_t> channel_counts[kChannels];

// Written by the event handlers and read by service(), under lock.
StaState sta_state = StaState::Off;
char sta_ssid[bench_protocol::kMaxSsidLength + 1] = {};
char sta_ip[16] = {};
int sta_reason = 0;
bool user_disconnect = false;
bool status_dirty = false;
uint32_t next_status_ms = 0;
wifi_ap_record_t ap_records[kMaxAps];

const char* state_name(StaState state) {
    switch (state) {
        case StaState::Off:
            return "off";
        case StaState::Idle:
            return "idle";
        case StaState::Connecting:
            return "connecting";
        case StaState::Connected:
            return "connected";
        case StaState::Failed:
            return "failed";
    }
    return "off";
}

const char* auth_name(wifi_auth_mode_t mode) {
    switch (mode) {
        case WIFI_AUTH_OPEN:
            return "open";
        case WIFI_AUTH_WEP:
            return "wep";
        case WIFI_AUTH_WPA_PSK:
            return "wpa";
        case WIFI_AUTH_WPA2_PSK:
            return "wpa2";
        case WIFI_AUTH_WPA_WPA2_PSK:
            return "wpa_wpa2";
        case WIFI_AUTH_WPA3_PSK:
            return "wpa3";
        case WIFI_AUTH_WPA2_WPA3_PSK:
            return "wpa2_wpa3";
        default:
            return "other";
    }
}

void set_state(StaState state) {
    sta_state = state;
    status_dirty = true;
}

void on_wifi_event(void*, esp_event_base_t base, int32_t id, void* data) {
    Locked guard;
    if (base == WIFI_EVENT && id == WIFI_EVENT_SCAN_DONE) {
        scan_running = false;
        scan_done = true;
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        const auto* event = static_cast<wifi_event_sta_disconnected_t*>(data);
        sta_ip[0] = '\0';
        if (user_disconnect) {
            set_state(StaState::Idle);
        } else {
            sta_reason = event->reason;
            set_state(StaState::Failed);
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const auto* event = static_cast<ip_event_got_ip_t*>(data);
        snprintf(sta_ip, sizeof(sta_ip), IPSTR, IP2STR(&event->ip_info.ip));
        set_state(StaState::Connected);
    }
}

void count_packet(void* buffer, wifi_promiscuous_pkt_type_t) {
    const auto* packet = static_cast<wifi_promiscuous_pkt_t*>(buffer);
    const unsigned channel = packet->rx_ctrl.channel;
    if (channel >= 1 && channel <= kChannels) {
        channel_counts[channel - 1].fetch_add(1, std::memory_order_relaxed);
    }
}

esp_err_t start_wifi() {
    if (wifi_started) {
        return ESP_OK;
    }
    ESP_RETURN_ON_ERROR(ensure_nvs(), kTag, "NVS failed");
    ESP_RETURN_ON_ERROR(esp_netif_init(), kTag, "netif init failed");
    esp_err_t result = esp_event_loop_create_default();
    ESP_RETURN_ON_FALSE(result == ESP_OK || result == ESP_ERR_INVALID_STATE, result, kTag,
                        "event loop failed");
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t config = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&config), kTag, "Wi-Fi init failed");
    ESP_RETURN_ON_ERROR(esp_wifi_set_storage(WIFI_STORAGE_RAM), kTag, "Wi-Fi storage failed");
    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_STA), kTag, "Wi-Fi mode failed");
    ESP_RETURN_ON_ERROR(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                            on_wifi_event, nullptr, nullptr),
                        kTag, "Wi-Fi event handler failed");
    ESP_RETURN_ON_ERROR(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                                            on_wifi_event, nullptr, nullptr),
                        kTag, "IP event handler failed");
    ESP_RETURN_ON_ERROR(esp_wifi_start(), kTag, "Wi-Fi start failed");
    esp_log_level_set("wifi", ESP_LOG_WARN);
    wifi_started = true;
    Locked guard;
    set_state(StaState::Idle);
    return ESP_OK;
}

void set_sniffer(bool on) {
    if (on == sniffer_on) {
        return;
    }
    for (auto& count : channel_counts) {
        count = 0;
    }
    if (on) {
        esp_wifi_set_promiscuous_rx_cb(count_packet);
    }
    esp_wifi_set_promiscuous(on);
    sniffer_on = on;
    next_channels_ms = now_ms() + kChannelReportMs;
    next_hop_ms = now_ms() + kHopPeriodMs;
}

void service_scan(uint32_t now) {
    if (scan_done.exchange(false)) {
        uint16_t count = kMaxAps;
        if (esp_wifi_scan_get_ap_records(&count, ap_records) != ESP_OK) {
            count = 0;
        }
        esp_wifi_clear_ap_list();
        std::sort(ap_records, ap_records + count,
                  [](const wifi_ap_record_t& one, const wifi_ap_record_t& two) {
                      return one.rssi > two.rssi;
                  });
        bench_protocol::WifiAp aps[kMaxAps];
        for (uint16_t index = 0; index < count; ++index) {
            bench_protocol::WifiAp& ap = aps[index];
            std::memset(&ap, 0, sizeof(ap));
            std::memcpy(ap.ssid, ap_records[index].ssid, bench_protocol::kMaxSsidLength);
            std::memcpy(ap.bssid, ap_records[index].bssid, sizeof(ap.bssid));
            ap.channel = ap_records[index].primary;
            ap.rssi = ap_records[index].rssi;
            ap.auth = auth_name(ap_records[index].authmode);
            const wifi_ap_record_t& record = ap_records[index];
            size_t phy_length = 0;
            if (record.phy_11b) {
                ap.phy[phy_length++] = 'b';
            }
            if (record.phy_11g) {
                ap.phy[phy_length++] = 'g';
            }
            if (record.phy_11n) {
                ap.phy[phy_length++] = 'n';
            }
            if (record.phy_11ax) {
                ap.phy[phy_length++] = 'x';
            }
            if (record.phy_lr) {
                ap.phy[phy_length++] = 'l';
            }
            ap.phy[phy_length] = '\0';
            ap.wps = record.wps;
            ap.second = record.second == WIFI_SECOND_CHAN_ABOVE   ? "above"
                        : record.second == WIFI_SECOND_CHAN_BELOW ? "below"
                                                                  : "none";
        }
        emit_line(bench_protocol::encode_wifi_scan_result(aps, count));
    }
    StaState state;
    {
        Locked guard;
        state = sta_state;
    }
    if (scan_period_ms == 0 || scan_running || state == StaState::Connecting ||
        static_cast<int32_t>(now - next_scan_ms) < 0) {
        return;
    }
    wifi_scan_config_t config = {};
    config.show_hidden = true;
    if (esp_wifi_scan_start(&config, false) == ESP_OK) {
        scan_running = true;
    }
    next_scan_ms = now + scan_period_ms;
}

void service_sniffer(uint32_t now, StaState state) {
    if (!sniffer_on) {
        return;
    }
    if (state != StaState::Connected && !scan_running &&
        static_cast<int32_t>(now - next_hop_ms) >= 0) {
        sniff_channel = sniff_channel % kChannels + 1;
        esp_wifi_set_channel(static_cast<uint8_t>(sniff_channel), WIFI_SECOND_CHAN_NONE);
        next_hop_ms = now + kHopPeriodMs;
    }
    if (static_cast<int32_t>(now - next_channels_ms) >= 0) {
        uint32_t counts[kChannels];
        for (size_t index = 0; index < kChannels; ++index) {
            counts[index] = channel_counts[index].exchange(0);
        }
        emit_line(bench_protocol::encode_wifi_channels(counts, kChannels, kChannelReportMs));
        next_channels_ms = now + kChannelReportMs;
    }
}

void service_status(uint32_t now) {
    bench_protocol::WifiStatus status = {};
    char ssid[sizeof(sta_ssid)];
    char ip[sizeof(sta_ip)];
    char reason[12] = {};
    {
        Locked guard;
        const bool periodic = sta_state == StaState::Connected &&
                              static_cast<int32_t>(now - next_status_ms) >= 0;
        if (!status_dirty && !periodic) {
            return;
        }
        status_dirty = false;
        next_status_ms = now + kStatusPeriodMs;
        status.state = state_name(sta_state);
        std::memcpy(ssid, sta_ssid, sizeof(ssid));
        std::memcpy(ip, sta_ip, sizeof(ip));
        if (sta_state == StaState::Failed) {
            snprintf(reason, sizeof(reason), "%d", sta_reason);
        }
    }
    status.ssid = ssid;
    status.ip = ip;
    status.reason = reason;
    wifi_ap_record_t info = {};
    if (std::strcmp(status.state, "connected") == 0 && esp_wifi_sta_get_ap_info(&info) == ESP_OK) {
        status.rssi = info.rssi;
        status.channel = info.primary;
    }
    emit_line(bench_protocol::encode_wifi_status(status));
}

#endif  // CONFIG_BENCH_RADIO_WIFI

#if CONFIG_BENCH_RADIO_BLE

struct BleEntry {
    bench_protocol::BleDevice device;
    uint32_t seen_ms;
    bool used;
};

bool ble_started = false;
std::atomic<bool> ble_wanted{false};
std::atomic<bool> ble_synced{false};
std::atomic<bool> ble_scanning{false};
std::atomic<bool> ble_active_scan{false};
uint32_t next_ble_ms = 0;
BleEntry ble_table[kBleTableSize];
bench_protocol::BleDevice ble_report[kBleTableSize];

void record_advertisement(const ble_gap_disc_desc& disc) {
    uint8_t address[6];
    // NimBLE stores the address least significant byte first.
    for (int index = 0; index < 6; ++index) {
        address[index] = disc.addr.val[5 - index];
    }
    ble_hs_adv_fields fields = {};
    const bool parsed = ble_hs_adv_parse_fields(&fields, disc.data, disc.length_data) == 0;
    const uint32_t now = now_ms();
    Locked guard;
    BleEntry* slot = nullptr;
    BleEntry* free_slot = nullptr;
    BleEntry* oldest = nullptr;
    for (BleEntry& entry : ble_table) {
        if (!entry.used) {
            if (free_slot == nullptr) {
                free_slot = &entry;
            }
            continue;
        }
        if (std::memcmp(entry.device.address, address, 6) == 0) {
            slot = &entry;
            break;
        }
        if (oldest == nullptr || entry.seen_ms < oldest->seen_ms) {
            oldest = &entry;
        }
    }
    if (slot == nullptr) {
        slot = free_slot != nullptr ? free_slot : oldest;
        std::memset(slot, 0, sizeof(*slot));
        std::memcpy(slot->device.address, address, 6);
        slot->device.company_id = -1;
        slot->device.tx_power = 127;
        slot->device.appearance = -1;
        slot->used = true;
    }
    slot->seen_ms = now;
    slot->device.rssi = disc.rssi;
    slot->device.adv_count++;
    slot->device.address_type = disc.addr.type;
    // A scan response tells nothing about connectable. The other advertising
    // PDU types do.
    if (disc.event_type != BLE_HCI_ADV_RPT_EVTYPE_SCAN_RSP) {
        slot->device.connectable = disc.event_type == BLE_HCI_ADV_RPT_EVTYPE_ADV_IND ||
                                   disc.event_type == BLE_HCI_ADV_RPT_EVTYPE_DIR_IND;
    }
    if (parsed && fields.tx_pwr_lvl_is_present) {
        slot->device.tx_power = fields.tx_pwr_lvl;
    }
    if (parsed && fields.appearance_is_present) {
        slot->device.appearance = fields.appearance;
    }
    if (parsed && fields.uuids16 != nullptr && fields.num_uuids16 > 0) {
        const size_t count = std::min<size_t>(fields.num_uuids16, bench_protocol::kMaxBleServices);
        for (size_t index = 0; index < count; ++index) {
            slot->device.services[index] = fields.uuids16[index].value;
        }
        slot->device.service_count = count;
    }
    if (parsed && fields.svc_data_uuid16 != nullptr && fields.svc_data_uuid16_len >= 2 &&
        slot->device.service_count < bench_protocol::kMaxBleServices) {
        const uint16_t uuid = fields.svc_data_uuid16[0] | fields.svc_data_uuid16[1] << 8;
        bool known = false;
        for (size_t index = 0; index < slot->device.service_count; ++index) {
            known = known || slot->device.services[index] == uuid;
        }
        if (!known) {
            slot->device.services[slot->device.service_count++] = uuid;
        }
    }
    if (parsed && fields.name != nullptr && fields.name_len > 0) {
        const size_t length = std::min<size_t>(fields.name_len, bench_protocol::kMaxBleNameLength);
        std::memcpy(slot->device.name, fields.name, length);
        slot->device.name[length] = '\0';
    }
    if (parsed && fields.mfg_data != nullptr && fields.mfg_data_len >= 2) {
        slot->device.company_id = fields.mfg_data[0] | fields.mfg_data[1] << 8;
        const size_t length =
            std::min<size_t>(fields.mfg_data_len, bench_protocol::kMaxBleManufacturerBytes);
        std::memcpy(slot->device.manufacturer, fields.mfg_data, length);
        slot->device.manufacturer_length = length;
    }
}

int on_gap_event(ble_gap_event* event, void*) {
    if (event->type == BLE_GAP_EVENT_DISC) {
        record_advertisement(event->disc);
    } else if (event->type == BLE_GAP_EVENT_DISC_COMPLETE) {
        ble_scanning = false;
    }
    return 0;
}

void start_discovery() {
    uint8_t own_address_type = 0;
    if (ble_hs_id_infer_auto(0, &own_address_type) != 0) {
        return;
    }
    ble_gap_disc_params params = {};
    params.passive = ble_active_scan ? 0 : 1;
    // Keep repeated advertisements, so the RSSI stays current.
    params.filter_duplicates = 0;
    if (ble_gap_disc(own_address_type, BLE_HS_FOREVER, &params, on_gap_event, nullptr) == 0) {
        ble_scanning = true;
    }
}

void on_sync() {
    ble_hs_util_ensure_addr(0);
    ble_synced = true;
    if (ble_wanted) {
        start_discovery();
    }
}

void host_task(void*) {
    nimble_port_run();
    nimble_port_freertos_deinit();
}

esp_err_t start_ble() {
    if (ble_started) {
        return ESP_OK;
    }
    ESP_RETURN_ON_ERROR(ensure_nvs(), kTag, "NVS failed");
    ESP_RETURN_ON_ERROR(nimble_port_init(), kTag, "NimBLE init failed");
    ble_hs_cfg.sync_cb = on_sync;
    nimble_port_freertos_init(host_task);
    esp_log_level_set("NimBLE", ESP_LOG_WARN);
    ble_started = true;
    return ESP_OK;
}

void service_ble(uint32_t now) {
    if (!ble_wanted || static_cast<int32_t>(now - next_ble_ms) < 0) {
        return;
    }
    next_ble_ms = now + kBleReportMs;
    size_t count = 0;
    {
        Locked guard;
        for (BleEntry& entry : ble_table) {
            if (!entry.used) {
                continue;
            }
            if (now - entry.seen_ms > kBleForgetMs) {
                entry.used = false;
                continue;
            }
            ble_report[count] = entry.device;
            ble_report[count].age_ms = now - entry.seen_ms;
            ++count;
        }
    }
    std::sort(ble_report, ble_report + count,
              [](const bench_protocol::BleDevice& one, const bench_protocol::BleDevice& two) {
                  return one.rssi > two.rssi;
              });
    emit_line(bench_protocol::encode_ble_devices(ble_report, std::min(count, kMaxBleReport)));
}

#endif  // CONFIG_BENCH_RADIO_BLE

}  // namespace

esp_err_t init(Emit emit) {
    emit_line = emit;
    lock = xSemaphoreCreateMutex();
    ESP_RETURN_ON_FALSE(lock != nullptr, ESP_ERR_NO_MEM, kTag, "no memory for the lock");
    return ESP_OK;
}

const char* configure(uint32_t wifi_scan_ms, bool sniffer, bool ble_scan, bool ble_active) {
#if CONFIG_BENCH_RADIO_WIFI
    if (wifi_scan_ms > 0 || sniffer) {
        if (start_wifi() != ESP_OK) {
            return "Wi-Fi start failed";
        }
    }
    if (wifi_started) {
        if (wifi_scan_ms == 0 && scan_running) {
            esp_wifi_scan_stop();
            scan_running = false;
        }
        scan_period_ms = wifi_scan_ms;
        next_scan_ms = now_ms();
        set_sniffer(sniffer);
    }
#else
    if (wifi_scan_ms > 0 || sniffer) {
        return "Wi-Fi is not in this build";
    }
#endif

#if CONFIG_BENCH_RADIO_BLE
    if (ble_scan) {
        if (start_ble() != ESP_OK) {
            return "BLE start failed";
        }
        ble_wanted = true;
        next_ble_ms = now_ms();
        if (ble_scanning && ble_active_scan != ble_active) {
            // A new scan type needs a new discovery procedure.
            ble_gap_disc_cancel();
            ble_scanning = false;
        }
        ble_active_scan = ble_active;
        if (ble_synced && !ble_scanning) {
            start_discovery();
        }
    } else {
        ble_wanted = false;
        if (ble_scanning) {
            ble_gap_disc_cancel();
            ble_scanning = false;
        }
    }
#else
    if (ble_scan) {
        return "Bluetooth is not in this build";
    }
    (void)ble_active;
#endif
    return nullptr;
}

void stop_scans() {
    configure(0, false, false, false);
}

const char* connect(const char* ssid, const char* password) {
#if CONFIG_BENCH_RADIO_WIFI
    if (start_wifi() != ESP_OK) {
        return "Wi-Fi start failed";
    }
    if (scan_running) {
        esp_wifi_scan_stop();
        scan_running = false;
    }
    wifi_config_t config = {};
    std::strncpy(reinterpret_cast<char*>(config.sta.ssid), ssid, sizeof(config.sta.ssid));
    std::strncpy(reinterpret_cast<char*>(config.sta.password), password,
                 sizeof(config.sta.password));
    config.sta.threshold.authmode = WIFI_AUTH_OPEN;
    {
        Locked guard;
        user_disconnect = true;
    }
    esp_wifi_disconnect();
    if (esp_wifi_set_config(WIFI_IF_STA, &config) != ESP_OK) {
        return "Wi-Fi config failed";
    }
    {
        Locked guard;
        user_disconnect = false;
        std::strncpy(sta_ssid, ssid, sizeof(sta_ssid) - 1);
        sta_ip[0] = '\0';
        set_state(StaState::Connecting);
    }
    if (esp_wifi_connect() != ESP_OK) {
        Locked guard;
        set_state(StaState::Failed);
        return "Wi-Fi connect failed";
    }
    return nullptr;
#else
    (void)ssid;
    (void)password;
    return "Wi-Fi is not in this build";
#endif
}

const char* disconnect() {
#if CONFIG_BENCH_RADIO_WIFI
    if (!wifi_started) {
        return nullptr;
    }
    {
        Locked guard;
        user_disconnect = true;
        set_state(StaState::Idle);
    }
    esp_wifi_disconnect();
    return nullptr;
#else
    return "Wi-Fi is not in this build";
#endif
}

void service(uint32_t now) {
#if CONFIG_BENCH_RADIO_WIFI
    if (wifi_started) {
        StaState state;
        {
            Locked guard;
            state = sta_state;
        }
        service_scan(now);
        service_sniffer(now, state);
        service_status(now);
    }
#endif
#if CONFIG_BENCH_RADIO_BLE
    service_ble(now);
#endif
    (void)now;
}

}  // namespace bench_radio
