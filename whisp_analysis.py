# -*- coding: utf-8 -*-
"""
/***************************************************************************
 whisp_analysis
                                 A QGIS plugin
 This plugin analyzes your geometries for deforestation risk through the OpenForis Whisp API
 ***************************************************************************/
"""

import subprocess
import sys
import os
import requests
import json
import tempfile

def check_and_install(package):
    """Check if a package is installed, and install it if not."""
    try:
        __import__(package)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

# Ensure required packages are installed
check_and_install("requests")

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QRadioButton,
    QLineEdit, QPushButton, QDialogButtonBox, QFileDialog, QProgressBar, QScrollArea, QWidget, QCheckBox
)


from qgis.core import QgsProject, QgsMapLayer, QgsVectorFileWriter, QgsVectorLayer, QgsMessageLog, Qgis, QgsField, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature
from qgis.PyQt.QtCore import QThread, pyqtSignal, QObject, QSettings, QTranslator, QCoreApplication, QVariant

from qgis.PyQt.QtGui import QIcon, QPixmap
from qgis.PyQt.QtWidgets import QAction, QProgressBar, QMessageBox

from .resources import *  # Qt resources
from .whisp_analysis_dialog import whisp_analysisDialog
import os.path
from PyQt5.QtCore import QVariant, QThread, pyqtSignal, QObject, Qt, QTimer







class InitializationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowIcon(QIcon(":/plugins/whisp_analysis/icon.png"))
        self.setWindowTitle("Whisp")
        layout = QVBoxLayout()
        self.label = QLabel("Initializing OpenForis Whisp, please wait...")
        layout.addWidget(self.label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        layout.addWidget(self.progress_bar)
        self.setLayout(layout)

# --- Worker to send the test geometry ---
class InitializationWorker(QObject):
    finished = pyqtSignal(dict)
    progress = pyqtSignal(str)

    def run(self):
        #self.progress.emit("Sending test geometry to Whisp API...")
        test_geojson = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {}}
            ]
        }
        url = "https://whisp.openforis.org/api/geojson"
        headers = {"Content-Type": "application/json"}
        try:
            response = requests.post(url, json=test_geojson, headers=headers)
            if response.status_code == 200:
                result = response.json()
                self.progress.emit("Initialization complete.")
                self.finished.emit(result)
            else:
                error_msg = f"Error {response.status_code}: {response.text}"
                self.progress.emit(error_msg)
                self.finished.emit({"error": error_msg})
        except Exception as e:
            error_msg = f"Request failed: {str(e)}"
            self.progress.emit(error_msg)
            self.finished.emit({"error": error_msg})



class LayerSelectionDialog(QDialog):
    def __init__(self, columns_mapping, parent=None, default_layer=None):
        super().__init__(parent)
        self.columns_mapping = columns_mapping  # store for later use
        self.setWindowTitle("Whisp")
        self.setWindowIcon(QIcon(":/plugins/whisp_analysis/icon.png"))
        layout = QVBoxLayout(self)

        # --- Header with Title and Whisp Logo ---
        headerLayout = QHBoxLayout()

        # Left part: Title and description.
        textLayout = QVBoxLayout()
        titleLabel = QLabel("Whisp")
        font = titleLabel.font()
        font.setPointSize(font.pointSize() * 2)  # Double the current font size.
        font.setBold(True)
        titleLabel.setFont(font)
        descriptionLabel = QLabel("Analyze your geometries for deforestation risk through the OpenForis Whisp API and output them as GeoJSON.")
        descriptionLabel.setWordWrap(True)
        textLayout.addWidget(titleLabel)
        textLayout.addWidget(descriptionLabel)
        headerLayout.addLayout(textLayout)

        headerLayout.addStretch()

        # Right part: the icon.
        logoLabel = QLabel()
        logoPixmap = QPixmap(":/plugins/whisp_analysis/icon.png")
        if not logoPixmap.isNull():
            scaledLogo = logoPixmap.scaled(
                int(logoPixmap.width() * 0.2),
                int(logoPixmap.height() * 0.2),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            logoLabel.setPixmap(scaledLogo)
        headerLayout.addWidget(logoLabel)

        layout.addLayout(headerLayout)
        layout.addSpacing(20)

        # --- Input Layer Selection ---
        layout.addWidget(QLabel("Select Input Layer:"))
        inputLayout = QHBoxLayout()
        self.inputCombo = QComboBox()
        layers = [layer for layer in QgsProject.instance().mapLayers().values()
                if layer.type() == QgsMapLayer.VectorLayer]
        for layer in layers:
            self.inputCombo.addItem(layer.name(), layer)
        inputLayout.addWidget(self.inputCombo)

        # Add a "Browse..." button for input layers.
        self.browseInputButton = QPushButton("Browse...")
        self.browseInputButton.setFixedWidth(100)
        inputLayout.addWidget(self.browseInputButton)
        layout.addLayout(inputLayout)

        # Use the passed default_layer, or fallback to the active layer from iface.
        if default_layer is None and hasattr(self, "iface"):
            default_layer = self.iface.activeLayer()
        if default_layer is not None:
            for index in range(self.inputCombo.count()):
                if self.inputCombo.itemData(index) == default_layer:
                    self.inputCombo.setCurrentIndex(index)
                    break

        self.inputCombo.currentIndexChanged.connect(self.updateOkButtonState)
        self.browseInputButton.clicked.connect(self.browseInputLayer)

        # Warning label for too many geometries.
        self.inputWarningLabel = QLabel("")
        self.inputWarningLabel.setStyleSheet("font-style: italic; color: red;")
        self.inputWarningLabel.setVisible(False)
        layout.addWidget(self.inputWarningLabel)

        # --- Output File Selection ---
        layout.addWidget(QLabel("Output File Name:"))
        fileLayout = QHBoxLayout()
        self.newFileLineEdit = QLineEdit()
        self.newFileBrowseButton = QPushButton("Browse...")
        self.newFileBrowseButton.setFixedWidth(100)
        fileLayout.addWidget(self.newFileLineEdit)
        fileLayout.addWidget(self.newFileBrowseButton)
        layout.addLayout(fileLayout)
        self.newFileBrowseButton.clicked.connect(self.browseNewFile)
        self.newFileLineEdit.textChanged.connect(self.updateOkButtonState)

        # --- Output Columns Selection ---
        layout.addWidget(QLabel("Select Output Columns:"))
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.checkbox_widget = QWidget()
        self.checkbox_widget.setObjectName("checkboxWidget")
        self.checkbox_layout = QVBoxLayout(self.checkbox_widget)
        self.checkboxes = {}
        for column in columns_mapping:
            checkbox = QCheckBox(column)
            checkbox.setChecked(True)
            checkbox.stateChanged.connect(self.updateOkButtonState)
            self.checkboxes[column] = checkbox
            self.checkbox_layout.addWidget(checkbox)
        self.scroll_area.setWidget(self.checkbox_widget)
        layout.addWidget(self.scroll_area)

        # --- Quick Selection Buttons ---
        btnLayout = QHBoxLayout()
        self.btnDeselectAll = QPushButton("Deselect all")
        self.btnSelectAll = QPushButton("Select all")
        self.btnSelectEUDR = QPushButton("Reduced Selection")
        btnLayout.addWidget(self.btnDeselectAll)
        btnLayout.addWidget(self.btnSelectAll)
        btnLayout.addWidget(self.btnSelectEUDR)
        layout.addLayout(btnLayout)
        self.btnDeselectAll.clicked.connect(self.deselectAll)
        self.btnSelectAll.clicked.connect(self.selectAll)
        self.btnSelectEUDR.clicked.connect(self.selectEUDRRelevant)

        # --- Dialog Buttons (OK/Cancel) ---
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        layout.addWidget(self.buttonBox)

        self.updateOkButtonState()
        self.applyCustomStyleSheet()

    def accept(self):

        # First, check CRS of the selected input layer.
        input_layer = self.inputCombo.currentData()
        if input_layer:
            source_crs = input_layer.crs()
            # Construct a detailed CRS string, e.g. "EPSG:3857 - Google Maps CRS"
            source_crs_str = f"{source_crs.authid()} - {source_crs.description()}"
            if source_crs.authid() != "EPSG:4326":
                msgBox = QMessageBox(self)
                msgBox.setIcon(QMessageBox.Warning)
                msgBox.setWindowTitle("CRS Conversion Warning")
                # Build HTML message with extra spacing and bold/italic for the CRS information.
                msg = (
                    f"<p>Your input geometry is in <b>{source_crs_str}</b>.</p>"
                    f"<p>The output will be in <b>EPSG:4326 - WGS84</b>.</p>"
                    f"<p>Do you wish to proceed?</p>"
                )
                msgBox.setTextFormat(Qt.RichText)
                msgBox.setText(msg)
                proceed_button = msgBox.addButton("Proceed", QMessageBox.AcceptRole)
                cancel_button = msgBox.addButton("Cancel", QMessageBox.RejectRole)
                msgBox.setDefaultButton(cancel_button)
                msgBox.exec_()
                if msgBox.clickedButton() == cancel_button:
                    # User cancelled the CRS warning; keep the dialog open.
                    return

        # Only prompt if we haven't already confirmed re‑whisp.
        if not getattr(self, 'allow_rewhisp', False):
            analysis_fields = set(self.columns_mapping.keys())
            input_layer = self.inputCombo.currentData()
            input_field_names = set(field.name() for field in input_layer.fields())
            missing_fields = analysis_fields.difference(input_field_names)
            # If five or fewer expected analysis fields are missing, assume it’s been whisped.
            if len(missing_fields) <= 5:
                msgBox = QMessageBox(self)
                msgBox.setIcon(QMessageBox.Warning)
                msgBox.setWindowTitle("Re‑whisp?")
                msgBox.setText("It seems you have previously whisped this input layer. Do you want to whisp it again?")
                rewhisp_button = msgBox.addButton("Re‑whisp", QMessageBox.AcceptRole)
                cancel_button = msgBox.addButton("Cancel", QMessageBox.RejectRole)
                msgBox.setDefaultButton(cancel_button)
                msgBox.exec_()
                if msgBox.clickedButton() == cancel_button:
                    # User chose to cancel; do not close the dialog.
                    return
                else:
                    # User chose to re‑whisp.
                    self.allow_rewhisp = True
                    # Disconnect the accepted signal so it doesn’t trigger the prompt again.
                    try:
                        self.buttonBox.accepted.disconnect(self.accept)
                    except Exception as e:
                        # In case it wasn’t connected or already disconnected.
                        pass
                    super().accept()
                    return
        # If already allowed or the check doesn't apply, accept normally.
        super().accept()






    def applyCustomStyleSheet(self):
        """
        Applies a style sheet that:
        - Forces the scroll area viewport to have a white background
        - Adds thinner horizontal lines (0.5px) under each checkbox that span the full width
        - Styles the scrollbar for a 3D-like look
        """

        # Make sure the scroll area viewport is white.
        self.scroll_area.viewport().setStyleSheet("background-color: white;")

        # Give the checkbox layout zero margins and spacing so lines can stretch edge to edge.
        self.checkbox_layout.setContentsMargins(0, 0, 0, 0)
        self.checkbox_layout.setSpacing(0)

        # Style the scrollbar with a simple 3D-like gradient.
        self.scroll_area.setStyleSheet("""
            QScrollBar:vertical {
                border: 1px solid #999999;
                background: #F0F0F0;
                width: 12px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #E4E4E4,
                    stop:0.5 #D1D1D1,
                    stop:0.5 #C7C7C7,
                    stop:1 #BFBFBF
                );
                min-height: 20px;
                border: 1px solid #AAA;
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical {
                height: 14px;
                subcontrol-position: bottom;
                subcontrol-origin: margin;
                border: 1px solid #999;
                background: #C2CCDF;
            }
            QScrollBar::sub-line:vertical {
                height: 14px;
                subcontrol-position: top;
                subcontrol-origin: margin;
                border: 1px solid #999;
                background: #C2CCDF;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: none;
            }
        """)

        # Thinner lines (0.5px) between checkboxes that span from left to right.
        # Removing margins ensures the line extends fully across the layout width.
        self.checkbox_widget.setStyleSheet("""
            QCheckBox {
                border-bottom: 0.1px solid #CCC;
                margin: 0;
                padding: 4px 0;
            }
        """)


    def updateOkButtonState(self):
        ok_button = self.buttonBox.button(QDialogButtonBox.Ok)
        file_ok = bool(self.newFileLineEdit.text().strip())
        # Check if at least one checkbox is selected.
        column_ok = any(cb.isChecked() for cb in self.checkboxes.values())
        ok_button.setEnabled(file_ok and column_ok)
    
    def browseInputLayer(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Geometry File",
            "",
            "Vector Files (*.shp *.geojson *.gpkg);;All Files (*)"
        )
        if file_path:
            new_layer = QgsVectorLayer(file_path, os.path.basename(file_path), "ogr")
            if not new_layer.isValid():
                QMessageBox.critical(self, "Error", "The selected file could not be loaded as a vector layer.")
            else:
                # Keep a reference so it isn’t garbage-collected.
                if not hasattr(self, 'extraInputLayers'):
                    self.extraInputLayers = []
                self.extraInputLayers.append(new_layer)
                
                self.inputCombo.addItem(new_layer.name(), new_layer)
                self.inputCombo.setCurrentIndex(self.inputCombo.count() - 1)





    def browseNewFile(self):
        # Start at the directory of the currently selected input layer (if any).
        selected_layer = self.inputCombo.currentData()
        default_dir = ""
        src = ""  # initialize src so it's always defined
        if selected_layer is not None:
            src = selected_layer.source()
            if src:
                default_dir = os.path.dirname(src)
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Select Output File",
            default_dir,
            "GeoJSON Files (*.geojson)"
        )
        if file_path:
            self.newFileLineEdit.setText(file_path)



    def deselectAll(self):
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(False)

    def selectAll(self):
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(True)

    def selectEUDRRelevant(self):
        # Adjust these names if needed (e.g., use "Plot_area_ha" instead of "Area").
        for col, checkbox in self.checkboxes.items():
            if col in {"Area", "ProducerCountry", "EUDR_risk"}:
                checkbox.setChecked(True)
            else:
                checkbox.setChecked(False)

    def getSelections(self):
        """Return the chosen input layer, output file path, and list of selected columns."""
        input_layer = self.inputCombo.currentData()
        output_file = self.newFileLineEdit.text()
        selected_columns = [col for col, cb in self.checkboxes.items() if cb.isChecked()]
        return input_layer, output_file, selected_columns







class WhispWorker(QObject):
    """Handles the API request in a background thread."""
    finished = pyqtSignal(dict)  # Signal to send back the API response
    progress = pyqtSignal(str)  # Signal to update progress messages

    def __init__(self, geojson):
        super().__init__()
        self.geojson = geojson

    def run(self):
        """Perform the API request in a separate thread."""
        self.progress.emit("Sending request to Whisp API...")
        url = "https://whisp.openforis.org/api/geojson"
        headers = {"Content-Type": "application/json"}

        try:
            response = requests.post(url, json=self.geojson, headers=headers)
            if response.status_code == 200:
                result = response.json()
                self.progress.emit("Whisp Analysis completed successfully.")
                self.finished.emit(result)  # Send response back to main thread
            else:
                error_msg = f"Error {response.status_code}: {response.text}"
                self.progress.emit(error_msg)
                self.finished.emit({"error": error_msg})
        except Exception as e:
            error_msg = f"Request failed: {str(e)}"
            self.progress.emit(error_msg)
            self.finished.emit({"error": error_msg})





class whisp_analysis:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor."""
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = self.tr(u"&Whisp Analysis")
        self.first_start = None
        self.whisp_columns_file = None  # This will store the path to our temp file

    def tr(self, message):
        """Translate a string."""
        return QCoreApplication.translate("whisp_analysis", message)

    def initGui(self):
        
        # Add toolbar / menu actions
        icon_path = ":/plugins/whisp_analysis/icon.png"
        self.add_action(
            icon_path=icon_path,
            text=self.tr("Start OpenForis Whisp"),
            callback=self.on_submit_geojson,
            status_tip=self.tr("Whisping..."),
            add_to_toolbar=True,
            add_to_menu=True,
            parent=self.iface.mainWindow()
        )
        self.first_start = True

    def add_action(self, icon_path, text, callback, status_tip=None, add_to_toolbar=True, add_to_menu=True, parent=None):
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setStatusTip(status_tip or "")
        self.actions.append(action)
        if add_to_toolbar:
            self.iface.addToolBarIcon(action)
        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)
        return action

    def initialize_whisp_columns(self):
        init_dialog = InitializationDialog(self.iface.mainWindow())
        # Set up the progress bar as a percentage bar.
        init_dialog.progress_bar.setRange(0, 100)
        init_dialog.progress_bar.setValue(0)

        # Create a timer that will increment the progress bar value.
        timer = QTimer(init_dialog)
        timer.setInterval(100)  # 100 ms intervals -> 100 steps for 10 seconds.
        timer.timeout.connect(lambda: init_dialog.progress_bar.setValue(
            min(init_dialog.progress_bar.value() + 1, 100)))
        timer.start()

        thread = QThread()
        worker = InitializationWorker()
        worker.moveToThread(thread)

        def on_worker_finished(result):
            timer.stop()  # Stop the progress timer.
            init_dialog.progress_bar.setValue(100)
            self.on_initialization_finished(result, init_dialog)

        worker.finished.connect(on_worker_finished)
        worker.progress.connect(lambda msg: init_dialog.label.setText(msg))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.started.connect(worker.run)

        self.init_thread = thread  # Keep a reference.
        thread.start()
        init_dialog.exec_()


    def on_initialization_finished(self, result, dialog):
        if "error" not in result:
            if "data" in result and result["data"]:
                first_row = result["data"][0]
                mapping = {}
                for key, value in first_row.items():
                    if key == "plotId":
                        mapping[key] = "int"
                    # Treat any numeric value as double regardless if it's an int or a float.
                    elif isinstance(value, (int, float)):
                        mapping[key] = "double"
                    else:
                        mapping[key] = "string"
                self.whisp_columns_mapping = mapping
                QgsMessageLog.logMessage(
                    f"Whisp columns mapping: {self.whisp_columns_mapping}",
                    "WhispAnalysis", Qgis.Info)
        else:
            QgsMessageLog.logMessage("Initialization error: " + result["error"],
                                    "WhispAnalysis", Qgis.Warning)
        dialog.accept()


    


    def unload(self):
        """Remove the plugin menu item and toolbar icon."""
        for action in self.actions:
            self.iface.removeToolBarIcon(action)
            self.iface.removePluginMenu(self.menu, action)

    
    
    def on_submit_geojson(self):
        # Trigger initialization if it hasn't been done yet.
        if not hasattr(self, 'whisp_columns_mapping') or not self.whisp_columns_mapping:
            self.initialize_whisp_columns()

        dialog = LayerSelectionDialog(self.whisp_columns_mapping, self.iface.mainWindow(), self.iface.activeLayer())
        if not dialog.exec_():
            return

        input_layer, output_file, selected_columns = dialog.getSelections()
        if not input_layer or not output_file or not selected_columns:
            QgsMessageLog.logMessage("Invalid selection. Ensure an input layer, output file, and at least one column are selected.",
                                    "WhispAnalysis", Qgis.Warning)
            return

        # Reproject the input layer to EPSG:4326
        input_layer = self.convert_to_epsg4326(input_layer)

        # Check if the input layer is already fully whisped
        existing_whisp_fields = set(field.name() for field in input_layer.fields()).intersection(set(self.whisp_columns_mapping.keys()))
        if len(existing_whisp_fields) == len(self.whisp_columns_mapping):
            QgsMessageLog.logMessage("Input layer already contains all Whisp fields. Creating a clean copy for re‑whisping.", "WhispAnalysis", Qgis.Info)
            input_layer = self.create_clean_layer(input_layer)


        # Process the output file name:
        import os
        if not os.path.isabs(output_file):
            input_source = input_layer.source()
            input_dir = os.path.dirname(input_source) if input_source else ""
            output_file = os.path.join(input_dir, output_file)
        if not output_file.lower().endswith(".geojson"):
            output_file += ".geojson"

        # Ensure the input layer has a "plotId" field.
        if "plotId" not in [field.name() for field in input_layer.fields()]:
            input_layer.startEditing()
            input_layer.dataProvider().addAttributes([QgsField("plotId", QVariant.Int)])
            input_layer.updateFields()
            input_layer.commitChanges()

        # Populate the "plotId" values.
        if not input_layer.isEditable():
            input_layer.startEditing()
        for idx, feature in enumerate(input_layer.getFeatures(), start=1):
            feature["plotId"] = idx
            input_layer.updateFeature(feature)
        input_layer.commitChanges()

        # Now create the output layer.
        output_layer = self.createNewOutputLayer(input_layer, output_file)
        if output_layer is None:
            QgsMessageLog.logMessage("Failed to create new output layer.", "WhispAnalysis", Qgis.Critical)
            return

        QgsProject.instance().addMapLayer(output_layer)
        self.selected_output_layer = output_layer

        self.ensure_required_fields(output_layer, selected_columns)
        geojson = self.get_selected_layer_as_geojson(input_layer)
        if not geojson:
            return


        # Create a modal progress dialog for the API call.
        processing_dialog = QDialog(self.iface.mainWindow())
        processing_dialog.setWindowTitle("Whisp")
        processing_dialog.setWindowIcon(QIcon(":/plugins/whisp_analysis/icon.png"))
        proc_layout = QVBoxLayout(processing_dialog)
        progress_label = QLabel("Sending request to Whisp API...")
        proc_layout.addWidget(progress_label)
        progress_bar = QProgressBar()

        import math
        num_features = input_layer.featureCount()
        # Total time = 10 sec (10000ms) plus 10ms per feature.
        total_time_ms = 10000 + (num_features * 10)
        ticks = int(math.ceil(total_time_ms / 100.0))  # with 100ms intervals.
        progress_bar.setRange(0, ticks)
        progress_bar.setValue(0)
        proc_layout.addWidget(progress_bar)

        # Add a Cancel button.
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_button = QPushButton("Cancel")
        btn_layout.addWidget(cancel_button)
        proc_layout.addLayout(btn_layout)

        processing_dialog.setLayout(proc_layout)
        processing_dialog.show()

        # After 3 seconds, change the label text.
        QTimer.singleShot(3000, lambda: progress_label.setText("Whisp API processing..."))

        # Create a timer that updates the progress bar every 100ms.
        timer = QTimer(processing_dialog)
        timer.setInterval(100)
        timer.timeout.connect(lambda: progress_bar.setValue(min(progress_bar.value() + 1, ticks)))
        timer.start()

        # Initialize a cancellation flag.
        self.cancelled = False

        def cancel_operation():
            self.cancelled = True
            timer.stop()
            try:
                if self.thread is not None and self.thread.isRunning():
                    self.thread.terminate()  # Forcefully terminate the thread.
            except Exception as e:
                QgsMessageLog.logMessage(f"Error terminating thread: {e}", "WhispAnalysis", Qgis.Warning)
            processing_dialog.reject()  # Close the progress dialog.
            for action in self.actions:
                action.setEnabled(True)
            QgsMessageLog.logMessage("User cancelled the API call.", "WhispAnalysis", Qgis.Warning)

        cancel_button.clicked.connect(cancel_operation)

        for action in self.actions:
            action.setEnabled(False)

        self.worker = WhispWorker(geojson)
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(lambda result: self.on_api_response_with_progress(result, timer, progress_bar, processing_dialog))
        self.worker.progress.connect(lambda msg: progress_label.setText(msg))
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()



    def on_api_response_with_progress(self, result, timer, progress_bar, processing_dialog):
        timer.stop()
        progress_bar.setValue(progress_bar.maximum())
        if self.cancelled:
            return
        processing_dialog.accept()  # Close the dialog.
        for action in self.actions:
            action.setEnabled(True)
        self.on_api_response(result)








    

    def createNewOutputLayer(self, input_layer, output_file):
        """
        Create a new vector layer for output using the input layer's settings.
        The new file is saved to output_file. This example assumes GeoJSON output.
        """
        # Set up the options for saving the file.
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GeoJSON"
        options.fileEncoding = "UTF-8"

        # Get the project's transform context.
        transform_context = QgsProject.instance().transformContext()

        # Write the vector layer using the new API.
        result = QgsVectorFileWriter.writeAsVectorFormatV2(
            input_layer,
            output_file,
            transform_context,
            options
        )

        # The result is a tuple (error code, error message).
        if result[0] == QgsVectorFileWriter.NoError:
            # Load the newly created layer.
            new_layer = QgsVectorLayer(output_file, os.path.basename(output_file), "ogr")
            return new_layer
        else:
            QgsMessageLog.logMessage("Error writing vector file: " + result[1], "WhispAnalysis", Qgis.Critical)
            return None


    def create_clean_layer(self, input_layer):
        # Filter out fields that are in the Whisp columns mapping
        original_fields = [field for field in input_layer.fields() if field.name() not in self.whisp_columns_mapping]
        
        # Convert the input layer's WKB type to a geometry type string.
        from qgis.core import QgsWkbTypes
        geom_type_str = QgsWkbTypes.displayString(input_layer.wkbType())
        crs = input_layer.crs().authid()
        
        # Create a new memory layer with the proper geometry type string and CRS.
        layer_str = f"{geom_type_str}?crs={crs}"
        clean_layer = QgsVectorLayer(layer_str, "clean_layer", "memory")
        
        if not clean_layer.isValid():
            QgsMessageLog.logMessage("Clean layer failed to initialize", "WhispAnalysis", Qgis.Critical)
            return None
        
        # Add only the original fields to the new layer.
        dp = clean_layer.dataProvider()
        dp.addAttributes(original_fields)
        clean_layer.updateFields()
        
        # Copy features from the input layer, keeping only the original attributes.
        features = []
        for feature in input_layer.getFeatures():
            new_feature = QgsFeature()
            new_feature.setGeometry(feature.geometry())
            attr_list = [feature[field.name()] for field in original_fields]
            new_feature.setAttributes(attr_list)
            features.append(new_feature)
        dp.addFeatures(features)
        clean_layer.updateExtents()
        
        return clean_layer



    def on_api_response(self, result):
        self.iface.messageBar().clearWidgets()  # Remove progress bar

        # Re-enable UI actions
        for action in self.actions:
            action.setEnabled(True)

        if "error" in result:
            QgsMessageLog.logMessage(f"Whisp API Error: {result['error']}", "WhispAnalysis", Qgis.Critical)
            QMessageBox.critical(self.iface.mainWindow(), "Whisp Analysis Failed", f"Error: {result['error']}")
            return

        QgsMessageLog.logMessage(f"Whisp API Response: {result}", "WhispAnalysis", Qgis.Info)

        # Update the selected output layer with API results.
        if self.selected_output_layer and "data" in result:
            self.append_data_to_layer(self.selected_output_layer, result["data"])
            msg_box = QMessageBox(self.iface.mainWindow())
            msg_box.setWindowIcon(QIcon(":/plugins/whisp_analysis/icon.png"))
            msg_box.setIcon(QMessageBox.Information)
            msg_box.setWindowTitle("Whisp")
            msg_box.setText("Geometries whisped successfully!\n\nValues appended to the output layer.")
            msg_box.exec_()






    def ensure_required_fields(self, layer, selected_columns):
        new_fields_added = False
        if not layer.isEditable():
            layer.startEditing()
        
        for field_name, type_str in self.whisp_columns_mapping.items():
            # Only add the field if it's one of the user-selected columns.
            if field_name in selected_columns:
                if field_name not in [field.name() for field in layer.fields()]:
                    if type_str == "int":
                        field_type = QVariant.Int
                    elif type_str == "double":
                        field_type = QVariant.Double
                    else:
                        field_type = QVariant.String
                    QgsMessageLog.logMessage(f"Adding new field: {field_name} (Type: {field_type})",
                                            "WhispAnalysis", Qgis.Info)
                    layer.addAttribute(QgsField(field_name, field_type))
                    new_fields_added = True
        
        if new_fields_added:
            layer.commitChanges()
            layer.startEditing()
            QgsMessageLog.logMessage("Committed new fields before API call.",
                                    "WhispAnalysis", Qgis.Info)





    def convert_to_epsg4326(self, layer):
        """Convert the selected layer to EPSG:4326 if it has a different CRS."""
        if not layer:
            QgsMessageLog.logMessage("No layer selected.", "WhispAnalysis", Qgis.Warning)
            return None

        source_crs = layer.crs()  # Get the current CRS
        target_crs = QgsCoordinateReferenceSystem("EPSG:4326")  # Define target CRS

        if source_crs.authid() != target_crs.authid():
            QgsMessageLog.logMessage(f"Reprojecting layer from {source_crs.authid()} to EPSG:4326...", "WhispAnalysis", Qgis.Info)

            # Determine the geometry type dynamically.
            from qgis.core import QgsWkbTypes
            geom_type_str = QgsWkbTypes.displayString(layer.wkbType())
            layer_name = layer.name() + " (EPSG:4326)"
            reprojected_layer = QgsVectorLayer(f"{geom_type_str}?crs=EPSG:4326", layer_name, "memory")

            # Copy fields from the original layer.
            reprojected_layer_data_provider = reprojected_layer.dataProvider()
            reprojected_layer_data_provider.addAttributes(layer.fields())
            reprojected_layer.updateFields()

            # Set up the coordinate transformation.
            transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())

            reprojected_layer.startEditing()
            for feature in layer.getFeatures():
                new_feature = QgsFeature()
                new_feature.setAttributes(feature.attributes())
                geom = feature.geometry()
                geom.transform(transform)
                new_feature.setGeometry(geom)
                reprojected_layer_data_provider.addFeature(new_feature)
            reprojected_layer.commitChanges()

            QgsMessageLog.logMessage("Layer reprojected to EPSG:4326 successfully!", "WhispAnalysis", Qgis.Info)
            # Do not add the reprojected layer to the project; it remains in memory.
            return reprojected_layer

        else:
            QgsMessageLog.logMessage("Layer is already in EPSG:4326.", "WhispAnalysis", Qgis.Info)
            return layer








    def get_selected_layer_as_geojson(self, layer):
        """Convert selected layer to EPSG:4326 if necessary and export it as GeoJSON, ensuring a 'plotId' field exists."""
        
        # Convert CRS to EPSG:4326 if needed
        layer = self.convert_to_epsg4326(layer)

        # Ensure 'plotId' field exists
        if "plotId" not in [field.name() for field in layer.fields()]:
            QgsMessageLog.logMessage("Adding 'plotId' field before export.", "WhispAnalysis", Qgis.Info)
            layer.startEditing()
            layer.addAttribute(QgsField("plotId", QVariant.Int))
            layer.commitChanges()
            layer.startEditing()

        QgsMessageLog.logMessage("Populating 'plotId' values.", "WhispAnalysis", Qgis.Info)
        layer.startEditing()
        for index, feature in enumerate(layer.getFeatures(), start=1):
            feature["plotId"] = index  # Store as integer
            QgsMessageLog.logMessage(f"Assigned plotId {index} to feature ID {feature.id()}", "WhispAnalysis", Qgis.Info)
            layer.updateFeature(feature)
        layer.commitChanges()

        # Convert layer features to GeoJSON
        features = []
        for feature in layer.getFeatures():
            features.append(feature.geometry().asJson())

        geojson = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": eval(f), "properties": {"plotId": feature["plotId"]}}
                for f, feature in zip(features, layer.getFeatures())
            ],
        }
        return geojson



    def submit_geojson(self, geojson):
        """Submit GeoJSON to the Whisp API and append results to the layer."""
        url = "https://whisp.openforis.org/api/geojson"
        headers = {"Content-Type": "application/json"}

        try:
            response = requests.post(url, json=geojson, headers=headers)
            if response.status_code == 200:
                result = response.json()
                QgsMessageLog.logMessage(f"API Response: {result}", "WhispAnalysis", Qgis.Info)
                if "data" in result and isinstance(result["data"], list):
                    layer = self.iface.activeLayer()
                    if layer:
                        self.append_data_to_layer(layer, result["data"])
                    else:
                        QgsMessageLog.logMessage("No layer selected to append data.", "WhispAnalysis", Qgis.Warning)
            else:
                QgsMessageLog.logMessage(
                    f"Failed to submit GeoJSON. Status code: {response.status_code}, Error: {response.text}",
                    "WhispAnalysis",
                    Qgis.Critical,
                )
        except Exception as e:
            QgsMessageLog.logMessage(f"Error during GeoJSON submission: {str(e)}", "WhispAnalysis", Qgis.Critical)

    

    def append_data_to_layer(self, layer, api_data):
        """Append API response data as attributes to the selected layer, ensuring correct data types."""
        if not layer.isEditable():
            layer.startEditing()

        # Get field data types
        field_types = {field.name(): field.type() for field in layer.fields()}

        for feature in layer.getFeatures():
            feature_plot_id = str(feature["plotId"])
            matched = False

            for row in api_data:
                if str(row["plotId"]) == feature_plot_id:
                    matched = True
                    QgsMessageLog.logMessage(f"Updating feature {feature.id()} with API data.", "WhispAnalysis", Qgis.Info)

                    for key, value in row.items():
                        if key in field_types:  # Ensure the field exists
                            if field_types[key] == QVariant.Double:  # Numeric field expected
                                try:
                                    if isinstance(value, dict):
                                        QgsMessageLog.logMessage(f"Value for field {key} is a dict; converting to string.", "WhispAnalysis", Qgis.Warning)
                                        feature[key] = str(value)
                                    else:
                                        value_float = float(value)
                                        # If the field is "Area" and the value is 0.01 or smaller, assign NULL.
                                        if key == "Area" and value_float <= 0.01:
                                            feature[key] = None
                                        else:
                                            if key in ["Centroid_lon", "Centroid_lat"]:
                                                feature[key] = round(value_float, 6)
                                            else:
                                                feature[key] = round(value_float, 3)
                                except (ValueError, TypeError) as e:
                                    QgsMessageLog.logMessage(f"Failed to convert {value} for {key}: {e}", "WhispAnalysis", Qgis.Warning)
                            elif field_types[key] == QVariant.Int:  # Integer field expected
                                try:
                                    feature[key] = int(value)
                                except (ValueError, TypeError) as e:
                                    QgsMessageLog.logMessage(f"Failed to convert {value} to integer for {key}: {e}", "WhispAnalysis", Qgis.Warning)
                            else:
                                feature[key] = str(value)  # For non-numeric fields, just store as string

                    layer.updateFeature(feature)
                    break  # Stop searching once a match is found

            if not matched:
                QgsMessageLog.logMessage(f"No match found for feature {feature.id()}", "WhispAnalysis", Qgis.Warning)

        layer.commitChanges()
        layer.triggerRepaint()
        QgsMessageLog.logMessage("Layer updated with API data.", "WhispAnalysis", Qgis.Info)








