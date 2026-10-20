"""The bench TUI in a web browser, with Pyodide.

- driver: a Textual driver that writes to a browser terminal (xterm.js) and
  reads its key and mouse data. It has no thread, because Pyodide has none.
- bridge: the functions that the JavaScript of the web pages calls.

Only bridge imports Pyodide modules, so the tests run the driver in CPython.
"""
