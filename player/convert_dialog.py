"""Dialogo de Archivo > Convertir / extraer audio (3.19): origen, formato y
destino, con barra de progreso y Cancelar. La conversion la hace
converter.ConvertJob en un Instance de libVLC aparte, sin cortar lo que se
esta reproduciendo."""

import os

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .converter import PROFILES, PROFILES_BY_KEY, ConvertJob, default_output_path


class ConvertDialog(QDialog):
    def __init__(self, source: str = "", parent=None, job_factory=ConvertJob, media_options=()):
        super().__init__(parent)
        self.setWindowTitle("Convertir / extraer audio")
        self.resize(560, 0)
        self._job_factory = job_factory
        self._media_options = list(media_options)
        self.job = None
        layout = QVBoxLayout(self)
        form = QFormLayout()
        source_row = QHBoxLayout()
        self.source_edit = QLineEdit(source)
        source_row.addWidget(self.source_edit)
        browse_source = QPushButton("Examinar…")
        browse_source.clicked.connect(self._browse_source)
        source_row.addWidget(browse_source)
        form.addRow("Origen:", source_row)
        self.profile_combo = QComboBox()
        for profile in PROFILES:
            self.profile_combo.addItem(profile.label, profile.key)
        self.profile_combo.currentIndexChanged.connect(self._suggest_output)
        form.addRow("Formato:", self.profile_combo)
        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        output_row.addWidget(self.output_edit)
        browse_output = QPushButton("Guardar como…")
        browse_output.clicked.connect(self._browse_output)
        output_row.addWidget(browse_output)
        form.addRow("Destino:", output_row)
        layout.addLayout(form)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        self.status_label = QLabel("La conversión no interrumpe lo que estás viendo.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.buttons = QDialogButtonBox()
        self.start_button = self.buttons.addButton("Convertir", QDialogButtonBox.ButtonRole.AcceptRole)
        self.close_button = self.buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self.start_button.clicked.connect(self.start)
        self.close_button.clicked.connect(self.reject)
        layout.addWidget(self.buttons)
        self._suggest_output()

    def profile(self):
        return PROFILES_BY_KEY[self.profile_combo.currentData()]

    def _suggest_output(self):
        source = self.source_edit.text().strip()
        if not source:
            return
        folder = os.path.dirname(self.output_edit.text()) if self.output_edit.text() else ""
        if "://" in source and not folder:
            folder = os.path.join(os.path.expanduser("~"), "Videos")
        self.output_edit.setText(default_output_path(source, self.profile(), folder))

    def _browse_source(self):
        path, _ = QFileDialog.getOpenFileName(self, "Archivo a convertir", self.source_edit.text())
        if path:
            self.source_edit.setText(path)
            self.output_edit.clear()
            self._suggest_output()

    def _browse_output(self):
        profile = self.profile()
        path, _ = QFileDialog.getSaveFileName(self, "Guardar como", self.output_edit.text(),
                                              f"{profile.label} (*{profile.extension})")
        if path:
            if not path.lower().endswith(profile.extension):
                path += profile.extension
            self.output_edit.setText(path)

    def start(self):
        source, output = self.source_edit.text().strip(), self.output_edit.text().strip()
        if not source or not output:
            self.status_label.setText("Falta el origen o el destino.")
            return
        if os.path.exists(output):
            self.status_label.setText("El destino ya existe: elige otro nombre.")
            return
        self.job = self._job_factory(source, output, self.profile(), self, media_options=self._media_options)
        self.job.progress.connect(lambda value: self.progress_bar.setValue(int(value * 1000)))
        self.job.finished.connect(self._on_finished)
        self.start_button.setEnabled(False)
        self.close_button.setText("Cancelar")
        self.status_label.setText("Convirtiendo…")
        self.job.start()

    def _on_finished(self, ok: bool, message: str):
        self.start_button.setEnabled(True)
        self.close_button.setText("Cerrar")
        self.status_label.setText(f"Listo: {message}" if ok else message)

    def reject(self):
        if self.job is not None and self.job.running:
            self.job.cancel()
            return
        super().reject()
