# Third-party dependencies and distribution boundary

This source snapshot does not vendor Qt/PySide6, Python, model weights, fonts or
other dependency implementations. Project source is offered under AGPL-3.0-only;
that choice does not relicense third-party components.

## Optional desktop dependency

The `desktop` extra declares `PySide6>=6.7`. The reviewed 6.12.0 installation of
PySide6, PySide6_Essentials, PySide6_Addons and shiboken6 reports
`LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`. Individual Qt modules and bundled
third-party components can have additional/different notices. Dependency license
texts remain with their distributions; a package-level expression is not a
complete binary redistribution audit. This source-use review uses the LGPL-3.0
route for PySide6; it does not select GPL-2.0-only as an AGPL compatibility
claim. The fresh environment also installed PySide6_Pdf and PySide6_WebEngine
6.12.0.140 transitively; this application does not import those modules and
this snapshot ships none of their binaries.

- https://doc.qt.io/qtforpython-6/licenses.html
- https://doc.qt.io/qt-6/licensing.html

Before bundling dependency binaries, select the applicable license route and
satisfy its notices, corresponding-source and modification/relinking obligations
where applicable. No Qt copyright is assigned to this project. The UI names
system fonts; this snapshot does not include their font files.

## Build and test tools

Setuptools (build requirement `>=77`) uses MIT. Pytest and pytest-qt use MIT;
packaging uses Apache-2.0 OR BSD-2-Clause; other transitive tools retain their
own licenses. These tools are not vendored in this source snapshot. Actual
installed versions and license metadata must be recorded for each release build.
Python itself retains its Python Software Foundation and bundled-component
licenses.

## Local model services and resources

Ollama/model software and individual model weights have their own terms.
Neither models nor Ollama are downloaded or included by this source release.
No model's availability establishes redistribution permission. External content
or future contributions require their own source/license disclosure.

This informational inventory does not replace required third-party license texts
or notices when shipping those components, and is not formal legal advice.
