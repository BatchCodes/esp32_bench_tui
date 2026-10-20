# Web TUI

The web TUI is the bench TUI in a web page. It runs the same Python code as the terminal TUI, in the browser, with [Pyodide](https://pyodide.org/). You do not need to install Python, Docker or ESP-IDF. The site has two pages:

| Page                                                                                 | What it does                                                                          | Browsers               |
| ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------- | ---------------------- |
| [TUI](https://batchcodes.github.io/esp32_bench_tui/tui/) (`/tui/`)                   | Connects to a board that runs the bench agent, over Web Serial.                       | Chrome, Edge and Opera |
| [Simulator](https://batchcodes.github.io/esp32_bench_tui/simulator/) (`/simulator/`) | Runs the TUI against the simulated bench agent, with no board. Use it to try the TUI. | all browsers           |

To install the bench agent on a board first, use the [web flasher](web_flasher.md).

## Use the TUI Page

1. Connect the board to the computer with a USB data cable.
2. Open the TUI page. The first visit loads about 15 MB (Pyodide, Textual and the host package). The browser keeps them for the next visit.
3. Choose a project:
   - **Open mode** shows the board picker, then puts an input on each free GPIO, the same as `./bench` with no configuration.
   - **An example** loads one of the files in [examples](../examples).
   - **Open a project file** loads a `.yaml` file from your computer.
4. Click **Connect board and start**, then select the serial port of the board.
5. Use the same keys as in the terminal TUI. Refer to the Keys section of the [README](../README.md).

The differences from the terminal TUI:

- `ctrl`+`s` downloads the project file. The page cannot write a file on your computer, so the TUI does not load the file again when it changes.
- `q` stops the TUI and closes the serial port. The page then shows the project choices again.
- If the cable comes out, the TUI shows "link lost". Connect the cable, then click **Reconnect the board**.
- The page does not remember the last board between visits.
- Log mode works with a project file that has `log_values`, for example [log_listen.yaml](../examples/log_listen.yaml). It is not tested on hardware yet.

The browser asks for the serial port each time you click the button. Close the terminal TUI, `idf.py monitor` and the flasher first, because only one program can open a serial port.

## How It Works

| Part                                                      | What it does                                                                                                                               |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| [web/app/bench.js](../web/app/bench.js)                   | Loads Pyodide, the wheels and the host package. Shows the project choices. Starts the TUI in an [xterm.js](https://xtermjs.org/) terminal. |
| [web/app/serial.js](../web/app/serial.js)                 | Opens the serial port with Web Serial, with DTR and RTS released. Feeds the bytes into the Python link, and writes the bytes of the link.  |
| [host/bench/web/driver.py](../host/bench/web/driver.py)   | A Textual driver that writes to the xterm.js terminal and reads its keys. It has no threads, because Pyodide has none.                     |
| [host/bench/web/bridge.py](../host/bench/web/bridge.py)   | Connects `serial.js` to a `BufferTransport` from [link.py](../host/bench/link.py).                                                         |
| [host/bench/web/session.py](../host/bench/web/session.py) | Loads the project, runs the board picker in open mode, then runs the bench TUI with the link.                                              |

The link uses the same code as the terminal TUI. In a terminal, a thread runs the link. In the browser, an asyncio task runs it, because Pyodide has no threads.

### The bundle

[build_web_bundle.sh](../scripts/build_web_bundle.sh) writes the Python bundle of the pages to `app/`:

- `bench_host.zip`: `host/bench`, `boards` and `examples`.
- `wheels/`: the wheels in [web/requirements.txt](../web/requirements.txt), Textual and all its dependencies, at fixed versions.
- `bundle.json`: the version and the file list.

The page installs the wheels with no dependency lookup, so a new release on PyPI cannot change the page. Pyodide and PyYAML come from the Pyodide CDN at a fixed version. To change the Textual version, update `web/requirements.txt` with all the dependencies of the new version.

[build_site.sh](../scripts/build_site.sh) calls `build_web_bundle.sh`. The `pages` job in [ci.yml](../.github/workflows/ci.yml) publishes the site.

### Test the pages locally

Web Serial works on `localhost` without HTTPS. Build the site with no firmware images, and serve it:

```bash
./scripts/build_site.sh --no-firmware --serve
```

Open <http://localhost:8000/simulator/> or <http://localhost:8000/tui/> in Chrome or Edge.

The Node tests in [tests/web](../tests/web) run the bundle in Pyodide, with no browser. One test connects `serial.js` to a fake serial port with the simulated agent behind it. The other runs a full simulator session. CI runs them in the `web_tests` job:

```bash
./scripts/ci.sh web-tests
```

## See also

- [Web flasher](web_flasher.md)
- [Wire protocol](protocol.md)
- [Project configuration](project_config.md)
