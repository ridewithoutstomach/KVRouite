from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton, QTextEdit
from core.gopro_extractor import extract_gopro_gps_multiple

class GoProExtractionThread(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(bool, object, str)  # success, gpx_data, message

    def __init__(self, video_paths):
        super().__init__()
        self.video_paths = video_paths

    def run(self):
        def progress_callback(msg):
            self.progress_signal.emit(msg)

        success, gpx_data, message = extract_gopro_gps_multiple(
            self.video_paths, 
            debug=True, 
            progress_callback=progress_callback
        )
        self.finished_signal.emit(success, gpx_data, message)

class GoProExtractionDialog(QDialog):
    def __init__(self, video_paths, parent=None):
        super().__init__(parent)
        self.video_paths = video_paths
        self.gpx_data = None
        self.extraction_success = False
        self.setWindowTitle("Extracting GoPro GPS Data...")
        self.setModal(True)
        self.resize(600, 400)

        layout = QVBoxLayout()

        self.status_label = QLabel("Preparing extraction...")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        layout.addWidget(self.progress_bar)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.on_cancel)
        layout.addWidget(self.cancel_button)

        self.setLayout(layout)

        self.thread = GoProExtractionThread(self.video_paths)
        self.thread.progress_signal.connect(self.update_progress)
        self.thread.finished_signal.connect(self.on_finished)
        self.thread.start()

    def update_progress(self, message):
        self.log_text.append(message)
        self.status_label.setText(message)

    def on_cancel(self):
        if self.thread.isRunning():
            self.thread.terminate()
            self.thread.wait()
        self.reject()

    def on_finished(self, success, gpx_data, message):
        self.extraction_success = success
        self.gpx_data = gpx_data
        self.log_text.append(message)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.status_label.setText("Extraction finished.")
        self.cancel_button.setText("Close")
        
        if success:
            self.accept()
        else:
            self.reject()

    def was_successful(self):
        return self.extraction_success

    def get_extracted_gpx_data(self):
        return self.gpx_data