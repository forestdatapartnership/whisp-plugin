# -*- coding: utf-8 -*-
"""
/***************************************************************************
 whisp_analysis
                                 A QGIS plugin
 This plugin analyzes your geometries for deforestation risk through the OpenForis Whisp API
 ***************************************************************************/
"""

from qgis.PyQt.QtCore import QThread, pyqtSignal, QObject

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


from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QProgressBar, QMessageBox
import requests
from qgis.core import QgsProject, QgsMessageLog, Qgis, QgsVectorLayer, QgsField
from .resources import *  # Qt resources
from .whisp_analysis_dialog import whisp_analysisDialog
import os.path
from PyQt5.QtCore import QVariant
import json


class whisp_analysis:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor."""
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = self.tr(u"&Whisp Analysis")
        self.first_start = None

    def tr(self, message):
        """Translate a string."""
        return QCoreApplication.translate("whisp_analysis", message)

    def initGui(self):
        """Create menu entries and toolbar icons in the QGIS GUI."""
        QgsMessageLog.logMessage("Initializing GUI...", "WhispAnalysis", Qgis.Info)

        icon_path = ":/plugins/whisp_analysis/icon.png"
        self.add_action(
            icon_path=icon_path,
            text=self.tr("Whisp selected layer"),
            callback=self.on_submit_geojson,
            status_tip=self.tr("Whisping..."),
            add_to_toolbar=True,
            add_to_menu=True,
            parent=self.iface.mainWindow()
        )

        self.first_start = True

    def add_action(self, icon_path, text, callback, status_tip=None, add_to_toolbar=True, add_to_menu=True, parent=None):
        """Add a toolbar icon to the toolbar."""
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

    def unload(self):
        """Remove the plugin menu item and toolbar icon."""
        for action in self.actions:
            self.iface.removeToolBarIcon(action)
            self.iface.removePluginMenu(self.menu, action)

    def on_submit_geojson(self):
        """Start the Whisp analysis process with a progress bar and background thread."""
        layer = self.iface.activeLayer()
        if not layer:
            QgsMessageLog.logMessage("No layer selected.", "WhispAnalysis", Qgis.Warning)
            return

        # Ensure required fields exist before making an API call
        self.ensure_required_fields(layer)

        # Generate GeoJSON
        geojson = self.get_selected_layer_as_geojson(layer)
        if not geojson:
            return

        # Show a progress message in QGIS status bar
        self.iface.messageBar().clearWidgets()
        progress_msg = self.iface.messageBar().createMessage("Whisping... Please wait.")
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 0)  # Indeterminate progress
        progress_msg.layout().addWidget(progress_bar)
        self.iface.messageBar().pushWidget(progress_msg, Qgis.Info)

        # Disable UI elements to prevent multiple clicks
        for action in self.actions:
            action.setEnabled(False)

        # Start background API request
        self.worker = WhispWorker(geojson)
        self.thread = QThread()
        
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_api_response)
        self.worker.progress.connect(lambda msg: self.iface.messageBar().pushMessage(msg, Qgis.Info))
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()


    def on_api_response(self, result):
        """Handles the API response and updates the layer with data."""
        self.iface.messageBar().clearWidgets()  # Remove progress bar

        # Re-enable UI actions
        for action in self.actions:
            action.setEnabled(True)

        if "error" in result:
            QgsMessageLog.logMessage(f"Whisp API Error: {result['error']}", "WhispAnalysis", Qgis.Critical)
            QMessageBox.critical(self.iface.mainWindow(), "Whisp Analysis Failed", f"Error: {result['error']}")
            return

        QgsMessageLog.logMessage(f"Whisp API Response: {result}", "WhispAnalysis", Qgis.Info)

        layer = self.iface.activeLayer()
        if layer and "data" in result:
            self.append_data_to_layer(layer, result["data"])
            
            # **Show success message**
            QMessageBox.information(
                self.iface.mainWindow(),
                "Whisp Analysis Complete",
                "Geometries whisped successfully!\nValues appended to attribute table."
            )



    def ensure_required_fields(self, layer):
        """Ensure all expected fields exist in the layer before making an API call, with correct data types."""
        
        # Define expected field types
        required_fields = [
            ("plotId", QVariant.Int),  # Force plotId to be Integer
            # Numeric fields
            ("Plot_area_ha", QVariant.Double), ("Centroid_lon", QVariant.Double), ("Centroid_lat", QVariant.Double),
            ("EUFO_2020", QVariant.Double), ("GLAD_Primary", QVariant.Double), ("TMF_undist", QVariant.Double),
            ("JAXA_FNF_2020", QVariant.Double), ("GFC_TC_2020", QVariant.Double), ("Forest_FDaP", QVariant.Double),
            ("ESA_TC_2020", QVariant.Double), ("TMF_plant", QVariant.Double), ("Oil_palm_Descals", QVariant.Double),
            ("Oil_palm_FDaP", QVariant.Double), ("Cocoa_FDaP", QVariant.Double), ("Cocoa_ETH", QVariant.Double),
            ("Cocoa_bnetd", QVariant.Double), ("Rubber_FDaP", QVariant.Double), ("Rubber_RBGE", QVariant.Double),
            # Time-series numeric fields (Deforestation, Degradation, Fire, Loss)
            *[(f"TMF_def_{year}", QVariant.Double) for year in range(2000, 2025)],
            *[(f"TMF_deg_{year}", QVariant.Double) for year in range(2000, 2025)],
            *[(f"GFC_loss_year_{year}", QVariant.Double) for year in range(2001, 2024)],
            *[(f"RADD_year_{year}", QVariant.Double) for year in range(2019, 2026)],
            *[(f"ESA_fire_{year}", QVariant.Double) for year in range(2001, 2021)],
            *[(f"MODIS_fire_{year}", QVariant.Double) for year in range(2000, 2025)],
            # Aggregate past/future impact
            ("TMF_deg_before_2020", QVariant.Double), ("TMF_def_before_2020", QVariant.Double),
            ("GFC_loss_before_2020", QVariant.Double), ("ESA_fire_before_2020", QVariant.Double),
            ("MODIS_fire_before_2020", QVariant.Double), ("RADD_before_2020", QVariant.Double),
            ("TMF_deg_after_2020", QVariant.Double), ("TMF_def_after_2020", QVariant.Double),
            ("GFC_loss_after_2020", QVariant.Double), ("MODIS_fire_after_2020", QVariant.Double),
            ("RADD_after_2020", QVariant.Double),
            # String fields (categorical data)
            ("geoid", QVariant.String), ("Geometry_type", QVariant.String), ("Country", QVariant.String),
            ("Admin_Level_1", QVariant.String), ("Unit", QVariant.String), ("In_waterbody", QVariant.String),
            ("Indicator_1_treecover", QVariant.String), ("Indicator_2_commodities", QVariant.String),
            ("Indicator_3_disturbance_before_2020", QVariant.String), ("Indicator_4_disturbance_after_2020", QVariant.String),
            ("EUDR_risk", QVariant.String)
        ]

        existing_fields = {field.name(): field.type() for field in layer.fields()}  # Dictionary of existing fields
        new_fields_added = False

        if not layer.isEditable():
            layer.startEditing()

        for field_name, field_type in required_fields:
            if field_name not in existing_fields:
                QgsMessageLog.logMessage(f"Adding new field: {field_name} (Type: {field_type})", "WhispAnalysis", Qgis.Info)
                layer.addAttribute(QgsField(field_name, field_type))
                new_fields_added = True

        if new_fields_added:
            layer.commitChanges()
            layer.startEditing()
            QgsMessageLog.logMessage("Committed new fields before API call.", "WhispAnalysis", Qgis.Info)



    def get_selected_layer_as_geojson(self, layer):
        """Export the selected layer as GeoJSON, ensuring a 'plotId' field exists."""
        if "plotId" not in [field.name() for field in layer.fields()]:
            QgsMessageLog.logMessage("Adding 'plotId' field before export.", "WhispAnalysis", Qgis.Info)
            layer.startEditing()
            layer.addAttribute(QgsField("plotId", QVariant.String))
            layer.commitChanges()
            layer.startEditing()

        QgsMessageLog.logMessage("Populating 'plotId' values.", "WhispAnalysis", Qgis.Info)
        layer.startEditing()
        for index, feature in enumerate(layer.getFeatures(), start=1):
            feature["plotId"] = str(index)
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
                            if field_types[key] == QVariant.Double:  # If it's a numeric field
                                try:
                                    if key in ["Centroid_lon", "Centroid_lat"]:  # Round to 6 decimals for these fields
                                        feature[key] = round(float(value), 6)
                                    else:  # Default to 3 decimal places for other numeric fields
                                        feature[key] = round(float(value), 3)
                                except ValueError:
                                    QgsMessageLog.logMessage(f"Failed to convert {value} to number for {key}", "WhispAnalysis", Qgis.Warning)
                            elif field_types[key] == QVariant.Int:  # Convert plotId to integer
                                try:
                                    feature[key] = int(value)
                                except ValueError:
                                    QgsMessageLog.logMessage(f"Failed to convert {value} to integer for {key}", "WhispAnalysis", Qgis.Warning)
                            else:
                                feature[key] = str(value)  # Keep as string for non-numeric fields

                    layer.updateFeature(feature)
                    break  # Stop searching once matched

            if not matched:
                QgsMessageLog.logMessage(f"No match found for feature {feature.id()}", "WhispAnalysis", Qgis.Warning)

        layer.commitChanges()
        layer.triggerRepaint()
        QgsMessageLog.logMessage("Layer updated with API data.", "WhispAnalysis", Qgis.Info)






