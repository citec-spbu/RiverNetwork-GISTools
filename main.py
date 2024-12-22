from qgis.core import (
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsPointXY,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsGeometry,
    QgsField,
    QgsFields,
    QgsSpatialIndex,
    QgsFeatureRequest,
    QgsRaster,
    QgsFeature,
    QgsApplication,
    QgsSymbol,
    QgsRendererCategory,
    QgsCategorizedSymbolRenderer,
    QgsProcessingFeatureSourceDefinition
)
from qgis.analysis import QgsNativeAlgorithms
from processing_saga_nextgen.saga_nextgen_plugin import SagaNextGenAlgorithmProvider
from qgis.PyQt.QtCore import QVariant, QCoreApplication, QEventLoop
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QInputDialog, QMessageBox
from qgis.PyQt.QtGui import QColor
from qgis.gui import QgsMapToolEmitPoint
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QPushButton, QDialog, QVBoxLayout, QLabel, QCheckBox
from osgeo import gdal
from pyproj import Transformer
import processing
import requests
import os
import numpy as np
import glob
from qgis.utils import iface
import math


class CustomDEMPlugin:

    project_folder = None

    def __init__(self, iface):
        self.iface = iface
        self.plugin_name = "RiverNETWORK"

    def initGui(self):
        #Для запуска плагина
        from qgis.PyQt.QtWidgets import QAction
        self.action = QAction(self.plugin_name, self.iface.mainWindow())
        self.action.triggered.connect(self.run_plugin)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&RiverNETWORK", self.action)

    def unload(self):
        #Удаление плагина
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginMenu("&RiverNETWORK", self.action)

    def run_plugin(self):
        #Код плагина
        CustomDEMPlugin.project_folder = QFileDialog.getExistingDirectory(
            None, "Выберите рабочую папку"
        )
        if not CustomDEMPlugin.project_folder:
            QMessageBox.warning(None, "Ошибка", "Рабочая папка не выбрана. Работа плагина прекращена.")
            return
        
        # Создать папку "work" внутри выбранной папки
        CustomDEMPlugin.project_folder = os.path.join(CustomDEMPlugin.project_folder, "work/")
        if not os.path.exists(CustomDEMPlugin.project_folder):
            os.makedirs(CustomDEMPlugin.project_folder)
        QMessageBox.information(None, "Папка установлена", f"Рабочая папка: {CustomDEMPlugin.project_folder}")
        CustomDEMPlugin.run_programm()

    
    '''
    ============== GITTING MAIN DEM =======================
    '''
    def get_main_def():
        CustomDEMPlugin.set_project_crs()
        CustomDEMPlugin.enable_processing_algorithms()
        CustomDEMPlugin.add_opentopo_layer()
        x, y = CustomDEMPlugin.get_coordinates()
        if x is None or y is None:
            return
        longitude, latitude = CustomDEMPlugin.transform_coordinates(x, y)
        bbox = [longitude - 0.5, latitude - 0.5, longitude + 0.5, latitude + 0.5]
        dem_path = CustomDEMPlugin.download_dem(bbox, CustomDEMPlugin.project_folder)
        dem_layer = CustomDEMPlugin.add_dem_layer(dem_path)
        return CustomDEMPlugin.reproject_dem(dem_path)
    
    # Установить систему координат проекта (EPSG:3857 - Pseudo-Mercator)
    def set_project_crs():
        crs = QgsCoordinateReferenceSystem("EPSG:3857")
        QgsProject.instance().setCrs(crs)

    # Включить встроенные алгоритмы обработки QGIS
    def enable_processing_algorithms():
        QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())
    
    # Добавить слой OpenTopoMap
    def add_opentopo_layer():
        opentopo_url = 'type=xyz&zmin=0&zmax=21&url=https://tile.opentopomap.org/{z}/{x}/{y}.png'
        opentopo_layer = QgsRasterLayer(opentopo_url, 'OpenTopoMap', 'wms')
        QgsProject.instance().addMapLayer(opentopo_layer)

    # Координаты озера в системе координат EPSG:3857
    #x_3857, y_3857 = 4316873, 7711643
    def get_coordinates():
        x, ok_x = QInputDialog.getDouble(None, "Координата X", "Введите координату X:", value=4316873, decimals=6)
        if not ok_x:
            QMessageBox.warning(None, "Ошибка", "Неправильная координата X. Работа плагина прекращена.")
            return None, None

        y, ok_y = QInputDialog.getDouble(None, "Координата Y", "Введите координату Y:", value=7711643, decimals=6)
        if not ok_y:
            QMessageBox.warning(None, "Ошибка", "Неправильная координата Y. Работа плагина прекращена.")
            return None, None

        return x, y
    # Преобразовать координаты в широту и долготу (EPSG:4326)
    def transform_coordinates(x, y):
        transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
        return transformer.transform(x, y)

    # Конфигурация запроса к OpenTopography API
    def download_dem(bbox, project_folder):
        api_key = 'c1fcbd0b2f691c736e3bf8c43e52a54d'
        url = (
            f"https://portal.opentopography.org/API/globaldem?"
            f"demtype=SRTMGL1"
            f"&south={bbox[1]}&north={bbox[3]}"
            f"&west={bbox[0]}&east={bbox[2]}"
            f"&outputFormat=GTiff"
            f"&API_Key={api_key}"
        )
        response = requests.get(url)

        output_path = f'{project_folder}srtm_output.tif'
        with open(output_path, 'wb') as f:
            f.write(response.content)

        return output_path

    # Репроекция DEM из EPSG:4326 в EPSG:3857
    def reproject_dem(dem_path):
        return processing.run("gdal:warpreproject", {
            'INPUT': dem_path,
            'SOURCE_CRS': QgsCoordinateReferenceSystem('EPSG:4326'),
            'TARGET_CRS': QgsCoordinateReferenceSystem('EPSG:3857'),
            'RESAMPLING': 0, 'NODATA': -9999, 'TARGET_RESOLUTION': 30,
            'OPTIONS': '', 'DATA_TYPE': 0, 'TARGET_EXTENT': None,
            'TARGET_EXTENT_CRS': None, 'MULTITHREADING': False,
            'EXTRA': '', 'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']

    # Добавить скачанный слой DEM в проект QGIS
    def add_dem_layer(dem_path):
        dem_layer = QgsRasterLayer(dem_path, "SRTM DEM Layer")
        QgsProject.instance().addMapLayer(dem_layer)
        return dem_layer

    # Загрузка алгоритмов SAGA
    def load_saga_algorithms():
        provider = SagaNextGenAlgorithmProvider()
        provider.loadAlgorithms()

        QgsApplication.processingRegistry().addProvider(provider=provider)

    # Использовать SAGA Fill Sinks для извлечения водосборов
    def fill_sinks(reprojected_relief, project_folder):
        return processing.run("sagang:fillsinkswangliu", {
            'ELEV': reprojected_relief, 'FILLED': 'TEMPORARY_OUTPUT',
            'FDIR': 'TEMPORARY_OUTPUT', 'WSHED': f'{CustomDEMPlugin.project_folder}basins.sdat',
            'MINSLOPE': 0.01})['WSHED']

    # Сохранить и добавить заполненные области водосбора в проект
    def add_basins_layer():
        basins = QgsRasterLayer(f'{CustomDEMPlugin.project_folder}basins.sdat', 'basins')
        QgsProject.instance().addMapLayer(basins)

    # Загрузить реки и ручьи
    def quickosm_query(key, value, extent):
        return processing.run('quickosm:buildqueryextent', {
            'KEY': key, 'VALUE': value, 'EXTENT': extent, 'TIMEOUT': 25})['OUTPUT_URL']

    def download_and_add_layer(url, layer_name, project_folder):
        file = processing.run("native:filedownloader", {
            'URL': url, 'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']
        layer = QgsVectorLayer(file + f'|layername={layer_name}', layer_name, "ogr")
        QgsProject.instance().addMapLayer(layer)
        return layer

    # Объединить слои рек и ручьев
    def merge_and_dissolve_layers(layers, project_folder):
        merged = processing.run("qgis:mergevectorlayers", {
            'LAYERS': layers, 'CRS': layers[0].crs(), 'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']
        dissolved = processing.run("native:dissolve", {
            'INPUT': merged, 'FIELD': [], 'SEPARATE_DISJOINT': False, 'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']
        return processing.run("native:multiparttosingleparts", {
            'INPUT': dissolved, 'OUTPUT': f'{CustomDEMPlugin.project_folder}merge_result.gpkg'})['OUTPUT']

    def calculate_coordinates(layer_path, project_folder):
        start_x = processing.run("native:fieldcalculator", {
            'INPUT': layer_path, 'FIELD_NAME': 'start_x',
            'FIELD_TYPE': 0, 'FIELD_LENGTH': 0, 'FIELD_PRECISION': 0,
            'FORMULA': 'x(start_point($geometry))', 'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']

        start_y = processing.run("native:fieldcalculator", {
            'INPUT': start_x, 'FIELD_NAME': 'start_y',
            'FIELD_TYPE': 0, 'FIELD_LENGTH': 0, 'FIELD_PRECISION': 0,
            'FORMULA': 'y(start_point($geometry))', 'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']

        end_x = processing.run("native:fieldcalculator", {
            'INPUT': start_y, 'FIELD_NAME': 'end_x',
            'FIELD_TYPE': 0, 'FIELD_LENGTH': 0, 'FIELD_PRECISION': 0,
            'FORMULA': 'x(end_point($geometry))', 'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']

        end_y = processing.run("native:fieldcalculator", {
            'INPUT': end_x, 'FIELD_NAME': 'end_y',
            'FIELD_TYPE': 0, 'FIELD_LENGTH': 0, 'FIELD_PRECISION': 0,
            'FORMULA': 'y(end_point($geometry))', 'OUTPUT': f'{CustomDEMPlugin.project_folder}rivers_with_points.gpkg'})['OUTPUT']

        return end_y

    # Добавить новые поля для хранения высотных данных
    def add_elevation_fields(layer):
        layer_provider = layer.dataProvider()
        layer_provider.addAttributes([QgsField("start_z", QVariant.Double)])
        layer_provider.addAttributes([QgsField("end_z", QVariant.Double)])
        layer.updateFields()

    # Начать редактирование и заполнение значений высоты
    def populate_elevation_data(layer, dem_layer):
        layer.startEditing()
        line_provider = layer.dataProvider()

        for feature in layer.getFeatures():
            geom = feature.geometry()
            polyline = geom.asMultiPolyline()[0] if geom.isMultipart() else geom.asPolyline()

            start_point = QgsPointXY(polyline[0])
            end_point = QgsPointXY(polyline[-1])

            start_z = dem_layer.dataProvider().identify(start_point, QgsRaster.IdentifyFormatValue)
            end_z = dem_layer.dataProvider().identify(end_point, QgsRaster.IdentifyFormatValue)

            start_z_value = start_z.results()[1] if start_z.isValid() else None
            end_z_value = end_z.results()[1] if end_z.isValid() else None

            feature['start_z'] = start_z_value
            feature['end_z'] = end_z_value
            line_provider.changeAttributeValues({
                feature.id(): {
                    line_provider.fields().indexOf('start_z'): start_z_value,
                    line_provider.fields().indexOf('end_z'): end_z_value
                }
            })

        layer.commitChanges()

    # Определить максимальную высоту для каждой линии
    def determine_maximum_heights(end_y, project_folder):
        max_z = processing.run("native:fieldcalculator", {
            'INPUT': end_y, 'FIELD_NAME': 'max_z',
            'FIELD_TYPE': 0, 'FIELD_LENGTH': 0, 'FIELD_PRECISION': 0,
            'FORMULA': 'if("start_z" > "end_z", "start_z", "end_z")',
            'OUTPUT': f'{project_folder}rivers_with_points.gpkg'})['OUTPUT']
        
        rivers_and_points = QgsVectorLayer(max_z, 'rivers_and_points')
        QgsProject.instance().addMapLayer(rivers_and_points)
        return rivers_and_points

    # Создать слой точек максимальной высоты
    def create_max_height_points_layer():
        point_layer = QgsVectorLayer("Point?crs=epsg:4326", "MaxHeightPoints", "memory")
        QgsProject.instance().addMapLayer(point_layer)
        layer_provider = point_layer.dataProvider()
        layer_provider.addAttributes([QgsField("x", QVariant.Double)])
        layer_provider.addAttributes([QgsField("y", QVariant.Double)])
        layer_provider.addAttributes([QgsField("z", QVariant.Double)])
        point_layer.updateFields()
        return point_layer
    
    # Получить ссылки на слои линий и точек
    def process_maximum_height_points(rivers_layer, point_layer):
        line_layer_name = 'rivers_and_points'
        layers = QgsProject.instance().mapLayersByName(line_layer_name)
        layer = layers[0]

        start_points = set()
        end_points = set()

        for feature in layer.getFeatures():
            start_x = feature['start_x']
            start_y = feature['start_y']
            end_x = feature['end_x']
            end_y = feature['end_y']

            if start_x is not None and start_y is not None:
                start_points.add((start_x, start_y))

            if end_x is not None and end_y is not None:
                end_points.add((end_x, end_y))

        fields = point_layer.fields()
        point_layer.startEditing()

        for feature in layer.getFeatures():
            if feature['max_z'] is not None:
                start_x = feature['start_x']
                start_y = feature['start_y']
                start_z = feature['start_z']
                end_x = feature['end_x']
                end_y = feature['end_y']
                end_z = feature['end_z']

                if start_x is not None and start_y is not None and start_z is not None:
                    start_point = (start_x, start_y)
                    if start_z == feature['max_z'] and start_point not in end_points:
                        point = QgsPointXY(start_x, start_y)
                        new_feature = QgsFeature()
                        new_feature.setFields(fields)
                        new_feature.setGeometry(QgsGeometry.fromPointXY(point))
                        new_feature['x'] = start_x
                        new_feature['y'] = start_y
                        new_feature['z'] = start_z
                        point_layer.addFeature(new_feature)

                if end_x is not None and end_y is not None and end_z is not None:
                    end_point = (end_x, end_y)
                    if end_z == feature['max_z'] and end_point not in start_points:
                        point = QgsPointXY(end_x, end_y)
                        new_feature = QgsFeature()
                        new_feature.setFields(fields)
                        new_feature.setGeometry(QgsGeometry.fromPointXY(point))
                        new_feature['x'] = end_x
                        new_feature['y'] = end_y
                        new_feature['z'] = end_z
                        point_layer.addFeature(new_feature)

        point_layer.commitChanges(True)

    def river():    
        CustomDEMPlugin.set_project_crs()
        CustomDEMPlugin.enable_processing_algorithms()
        CustomDEMPlugin.add_opentopo_layer()
        x, y = CustomDEMPlugin.get_coordinates()
        if x is None or y is None:
            return
        longitude, latitude = CustomDEMPlugin.transform_coordinates(x, y)
        radius = 0.5
        xmin, ymin = longitude - radius, latitude - radius
        xmax, ymax = longitude + radius, latitude + radius
        # Конфигурация запроса к OpenTopography API
        api_key = 'c1fcbd0b2f691c736e3bf8c43e52a54d'
        url = (
            f"https://portal.opentopography.org/API/globaldem?"
            f"demtype=SRTMGL1"
            f"&south={ymin}&north={ymax}"
            f"&west={xmin}&east={xmax}"
            f"&outputFormat=GTiff"
            f"&API_Key={api_key}"
        )
        response = requests.get(url)

        # Сохранить скачанный DEM на диск
        output_path = f'{CustomDEMPlugin.project_folder}srtm_output.tif'
        with open(output_path, 'wb') as f:
            f.write(response.content)

        # Добавить скачанный слой DEM в проект QGIS
        dem_layer = QgsRasterLayer(output_path, "SRTM DEM Layer")
        QgsProject.instance().addMapLayer(dem_layer)

        # Репроекция DEM из EPSG:4326 в EPSG:3857
        reprojected_relief = processing.run("gdal:warpreproject", {
            'INPUT': output_path,
            'SOURCE_CRS': QgsCoordinateReferenceSystem('EPSG:4326'),
            'TARGET_CRS': QgsCoordinateReferenceSystem('EPSG:3857'),
            'RESAMPLING': 0, 'NODATA': -9999, 'TARGET_RESOLUTION': 30,
            'OPTIONS': '', 'DATA_TYPE': 0, 'TARGET_EXTENT': None,
            'TARGET_EXTENT_CRS': None, 'MULTITHREADING': False,
            'EXTRA': '', 'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']


        CustomDEMPlugin.load_saga_algorithms()
        # Использовать SAGA Fill Sinks для извлечения водосборов
        filled_relief = processing.run("sagang:fillsinkswangliu", {
            'ELEV': reprojected_relief, 'FILLED': 'TEMPORARY_OUTPUT',
            'FDIR': 'TEMPORARY_OUTPUT', 'WSHED': f'{CustomDEMPlugin.project_folder}basins.sdat',
            'MINSLOPE': 0.01})['WSHED']

        # Сохранить и добавить заполненные области водосбора в проект
        basins = QgsRasterLayer(f'{CustomDEMPlugin.project_folder}basins.sdat', 'basins')
        QgsProject.instance().addMapLayer(basins)

        # Использовать QuickOSM для запроса данных о водных путях на заданной территории
        bbox = "4261842, 4372940, 7611625, 7813231"

        # Загрузить реки
        query = processing.run('quickosm:buildqueryextent', {
            'KEY': 'waterway', 'VALUE': 'river', 'EXTENT': bbox, 'TIMEOUT': 25})
        file = processing.run("native:filedownloader", {
            'URL': query['OUTPUT_URL'], 'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']
        rivers = iface.addVectorLayer(file + '|layername=lines', "rivers", "ogr")

        # Загрузить ручьи
        query = processing.run('quickosm:buildqueryextent', {
            'KEY': 'waterway', 'VALUE': 'stream', 'EXTENT': bbox, 'TIMEOUT': 25})
        file = processing.run("native:filedownloader", {
            'URL': query['OUTPUT_URL'], 'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']
        streams = iface.addVectorLayer(file + '|layername=lines', "streams", "ogr")

        # Объединить слои рек и ручьев
        layer1 = QgsProject.instance().mapLayersByName("rivers")[0]
        layer2 = QgsProject.instance().mapLayersByName("streams")[0]
        merge_result = processing.run("qgis:mergevectorlayers", {
            'LAYERS': [layer1, layer2], 'CRS': layer1.crs(),
            'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']
        merge_result = processing.run("native:dissolve",
                                {'INPUT': merge_result, 'FIELD': [], 'SEPARATE_DISJOINT': False, 'OUTPUT': 'TEMPORARY_OUTPUT'})[
            'OUTPUT']
        merge_result = processing.run("native:multiparttosingleparts", {'INPUT': merge_result, 'OUTPUT': f'{CustomDEMPlugin.project_folder}merge_result.gpkg'})['OUTPUT']

        # Добавить объединенный слой в проект
        rivers_merged = QgsVectorLayer(f'{CustomDEMPlugin.project_folder}merge_result.gpkg', 'rivers_merged')
        QgsProject.instance().addMapLayer(rivers_merged)

        # Загрузить полигональные данные о водных объектах
        query = processing.run('quickosm:buildqueryextent', {
            'KEY': 'natural', 'VALUE': 'water', 'EXTENT': bbox, 'TIMEOUT': 25})
        file = processing.run("native:filedownloader", {
            'URL': query['OUTPUT_URL'], 'OUTPUT': f'{CustomDEMPlugin.project_folder}water.gpkg'})['OUTPUT']
        water = iface.addVectorLayer(file + '|layername=multipolygons', "water", "ogr")

        # Рассчитать координаты начальных и конечных точек линий
        start_x = processing.run("native:fieldcalculator", {
            'INPUT': f'{CustomDEMPlugin.project_folder}merge_result.gpkg', 'FIELD_NAME': 'start_x',
            'FIELD_TYPE': 0, 'FIELD_LENGTH': 0, 'FIELD_PRECISION': 0,
            'FORMULA': 'x(start_point($geometry))', 'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']

        start_y = processing.run("native:fieldcalculator", {
            'INPUT': start_x, 'FIELD_NAME': 'start_y',
            'FIELD_TYPE': 0, 'FIELD_LENGTH': 0, 'FIELD_PRECISION': 0,
            'FORMULA': 'y(start_point($geometry))', 'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']

        end_x = processing.run("native:fieldcalculator", {
            'INPUT': start_y, 'FIELD_NAME': 'end_x',
            'FIELD_TYPE': 0, 'FIELD_LENGTH': 0, 'FIELD_PRECISION': 0,
            'FORMULA': 'x(end_point($geometry))', 'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']

        end_y = processing.run("native:fieldcalculator", {
            'INPUT': end_x, 'FIELD_NAME': 'end_y',
            'FIELD_TYPE': 0, 'FIELD_LENGTH': 0, 'FIELD_PRECISION': 0,
            'FORMULA': 'y(end_point($geometry))', 'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']

        # Добавить новые поля для хранения высотных данных
        layer_provider = end_y.dataProvider()
        layer_provider.addAttributes([QgsField("start_z", QVariant.Double)])
        layer_provider.addAttributes([QgsField("end_z", QVariant.Double)])
        end_y.updateFields()

        # Начать редактирование и заполнение значений высоты
        end_y.startEditing()
        line_provider = end_y.dataProvider()

        for feature in end_y.getFeatures():
            geom = feature.geometry()
            if geom.isMultipart():
                polyline = geom.asMultiPolyline()[0]
            else:
                polyline = geom.asPolyline()

            start_point = QgsPointXY(polyline[0])
            end_point = QgsPointXY(polyline[-1])

            # Высотные данные начальной точки
            start_z = dem_layer.dataProvider().identify(start_point, QgsRaster.IdentifyFormatValue)

            start_z_idx = line_provider.fields().indexOf('start_z')
            if start_z.isValid():
                start_z_value = start_z.results()[1]
                feature['start_z'] = start_z_value

            # Высотные данные конечной точки
            end_z = dem_layer.dataProvider().identify(end_point, QgsRaster.IdentifyFormatValue)
            end_z_idx = line_provider.fields().indexOf('end_z')
            if end_z.isValid():
                end_z_value = end_z.results()[1]
                feature['end_z'] = end_z_value

            line_provider.changeAttributeValues({feature.id(): {start_z_idx: start_z_value, end_z_idx: end_z_value}})

        end_y.commitChanges()

        # Определить максимальную высоту для каждой линии
        max_z = processing.run("native:fieldcalculator", {
            'INPUT': end_y, 'FIELD_NAME': 'max_z',
            'FIELD_TYPE': 0, 'FIELD_LENGTH': 0, 'FIELD_PRECISION': 0,
            'FORMULA': 'if("start_z" > "end_z", "start_z", "end_z")',
            'OUTPUT': f'{CustomDEMPlugin.project_folder}rivers_with_points.gpkg'})['OUTPUT']

        rivers_and_points = QgsVectorLayer(max_z, 'rivers_and_points')
        QgsProject.instance().addMapLayer(rivers_and_points)

        # Создать слой точек максимальной высоты
        point_layer = QgsVectorLayer("Point?crs=epsg:4326", "MaxHeightPoints", "memory")
        QgsProject.instance().addMapLayer(point_layer)
        layer_provider = point_layer.dataProvider()
        layer_provider.addAttributes([QgsField("x", QVariant.Double)])
        layer_provider.addAttributes([QgsField("y", QVariant.Double)])
        layer_provider.addAttributes([QgsField("z", QVariant.Double)])
        point_layer.updateFields()
        fields = point_layer.fields()

        # Получить ссылки на слои линий и точек
        line_layer_name = 'rivers_and_points'
        layers = QgsProject.instance().mapLayersByName(line_layer_name)
        layer = layers[0]

        point_layer_name = 'MaxHeightPoints'
        pointLayers = QgsProject.instance().mapLayersByName(point_layer_name)
        pointLayer = pointLayers[0]



        # Сначала собираем все конечные и начальные точки
        start_points = set()
        end_points = set()

        for feature in layer.getFeatures():
            start_x = feature['start_x']
            start_y = feature['start_y']
            end_x = feature['end_x']
            end_y = feature['end_y']

            if start_x is not None and start_y is not None:
                start_points.add((start_x, start_y))

            if end_x is not None and end_y is not None:
                end_points.add((end_x, end_y))

        pointLayer.startEditing()

        for feature in layer.getFeatures():
            if feature['max_z'] is not None:
                start_x = feature['start_x']
                start_y = feature['start_y']
                start_z = feature['start_z']
                end_x = feature['end_x']
                end_y = feature['end_y']
                end_z = feature['end_z']

                # Проверка начальной точки
                if start_x is not None and start_y is not None and start_z is not None:
                    start_point = (start_x, start_y)
                    if start_z == feature['max_z'] and start_point not in end_points:
                        point = QgsPointXY(start_x, start_y)
                        new_feature = QgsFeature()
                        new_feature.setFields(fields)
                        new_feature.setGeometry(QgsGeometry.fromPointXY(point))
                        new_feature['x'] = start_x
                        new_feature['y'] = start_y
                        new_feature['z'] = start_z
                        pointLayer.addFeature(new_feature)

                # Проверка конечной точки
                if end_x is not None and end_y is not None and end_z is not None:
                    end_point = (end_x, end_y)
                    if end_z == feature['max_z'] and end_point not in start_points:
                        point = QgsPointXY(end_x, end_y)
                        new_feature = QgsFeature()
                        new_feature.setFields(fields)
                        new_feature.setGeometry(QgsGeometry.fromPointXY(point))
                        new_feature['x'] = end_x
                        new_feature['y'] = end_y
                        new_feature['z'] = end_z
                        pointLayer.addFeature(new_feature)

        # Завершение редактирования и сохранение изменений
        pointLayer.commitChanges(True)

        

    '''
    ============================= GETTING USERS' AREA=============================
    '''

    # 1. Сбор точек пользователем
    class PointCollector(QgsMapToolEmitPoint):
        collection_complete = pyqtSignal()  # Сигнал завершения сбора точек

        def __init__(self, canvas):
            super().__init__(canvas)
            self.canvas = canvas
            self.points = []
            
            # Создаем временный слой для отображения точек
            self.point_layer = QgsVectorLayer("Point?crs=EPSG:3857", "Selected Points", "memory")
            self.point_provider = self.point_layer.dataProvider()
            QgsProject.instance().addMapLayer(self.point_layer)
            
            # Список аннотаций для отображения координат
            self.annotations = []

        def canvasPressEvent(self, event):
            point = self.toMapCoordinates(event.pos())
            self.points.append(point)
            print(f"Точка выбрана: {point}")
            
            # Добавляем точку в слой
            point_feature = QgsFeature()
            point_feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(point)))
            self.point_provider.addFeatures([point_feature])
            self.point_layer.updateExtents()
            self.point_layer.triggerRepaint()

        def get_points(self):
            return self.points

        def complete_collection(self):
            # Генерируем сигнал, чтобы уведомить об окончании сбора
            self.collection_complete.emit()

    # 2. Преобразование точек в полигон
    def create_polygon_from_points(points):
        # Преобразуем список точек в полигон (замкнутую геометрию)
        qgs_points = [QgsPointXY(pt.x(), pt.y()) for pt in points]  # Преобразуем в QgsPointXY
        polygon = QgsGeometry.fromPolygonXY([qgs_points])  # Обратите внимание на вложение в список
        return polygon

    # 3. Добавление полигона в слой
    def add_polygon_to_layer(polygon):
        # Создаем слой в памяти и добавляем полигон
        polygon_layer = QgsVectorLayer('Polygon?crs=EPSG:3857', 'Selected Region', 'memory')
        polygon_layer_data = polygon_layer.dataProvider()
        
        polygon_feature = QgsFeature()
        polygon_feature.setGeometry(polygon)
        polygon_layer_data.addFeatures([polygon_feature])

        QgsProject.instance().addMapLayer(polygon_layer)
        print("Полигон добавлен в проект.")
        return polygon_layer

    # 4. Обрезка DEM с использованием полигона
    def clip_dem_with_polygon(dem_layer, polygon_layer, masked_dem_output_path):
        # Параметры буфера
        buffer_distance = 100  # Задайте отступ в метрах или единицах CRS маски
        buffered_mask = os.path.join(CustomDEMPlugin.project_folder, "buffered_mask.shp")

        # Создание буфера
        processing.run("native:buffer", {
            'INPUT': polygon_layer,  # Исходная маска
            'DISTANCE': buffer_distance,  # Отступ
            'SEGMENTS': 5,  # Количество сегментов для сглаживания (можно увеличить для кругов)
            'END_CAP_STYLE': 0,  # Открытая граница
            'JOIN_STYLE': 0,  # Стыковка углов (например, круглая)
            'MITER_LIMIT': 2,
            'DISSOLVE': False,
            'OUTPUT': buffered_mask
        })
        # Убедитесь, что буфер был успешно создан
        print(f'Буфер сохранен в: {buffered_mask}')
        # Используем инструмент GDAL для обрезки DEM с использованием полигона
        processing.run("gdal:cliprasterbymasklayer", {
            'INPUT': dem_layer,
            'MASK': QgsProcessingFeatureSourceDefinition(buffered_mask, selectedFeaturesOnly=False),
            'CROP_TO_CUTLINE': True,       # Оставляем все пиксели, пересекающие границу полигона
            'ALL_TOUCHED': True,            # Включаем все пиксели, хотя бы частично затронутые полигоном
            'KEEP_RESOLUTION': True,       # Preserve the resolution of the DEM
            'OUTPUT': masked_dem_output_path
        })
        print(f"Обрезка завершена. Выходной файл: {masked_dem_output_path}")

    # Основная функция для выполнения всего процесса
    def process_dem_with_polygon(main_dem_file_path, masked_dem_output_path):
        # 1. Загружаем DEM слой
        dem_layer = QgsRasterLayer(main_dem_file_path, "SRTM DEM Layer")
        if not dem_layer.isValid():
            print("Ошибка загрузки DEM слоя.")
            return
        
        QgsProject.instance().addMapLayer(dem_layer)
        print("DEM слой загружен.")
        
        # 2. Начинаем сбор точек
        collector = CustomDEMPlugin.start_point_collection()

        # 3. Добавляем кнопку завершения
        CustomDEMPlugin.add_finish_button(collector, dem_layer, masked_dem_output_path)
        
        # 4. Ожидаем завершения обработки
        CustomDEMPlugin.wait_for_process()

    # Добавление кнопки завершения в интерфейс
    def add_finish_button(collector, dem_layer, masked_dem_output_path):
        finish_button = QPushButton("Завершить сбор точек", iface.mainWindow())
        finish_button.setGeometry(10, 50, 200, 30)  # Позиция и размер кнопки
        finish_button.show()

        def on_button_click():
            collector.complete_collection()
            finish_button.deleteLater()  # Убираем кнопку после завершения
            CustomDEMPlugin.handle_points_collection(collector, dem_layer, masked_dem_output_path)
            process_complete()  # Сигнализируем об окончании процесса

        finish_button.clicked.connect(on_button_click)

    # Ожидание завершения процесса
    def wait_for_process():
        loop = QEventLoop()

        def stop_waiting():
            loop.quit()

        global process_complete
        process_complete = stop_waiting
        loop.exec_()
        
    # Обработчик завершения сбора точек
    def handle_points_collection(collector, dem_layer, masked_dem_output_path):
        selected_points = collector.get_points()
        
        if len(selected_points) < 3:
            print("Для создания полигона необходимо выбрать хотя бы 3 точки.")
            return

        # 5. Создаем полигон из точек
        polygon = CustomDEMPlugin.create_polygon_from_points(selected_points)
        
        # 6. Добавляем полигон в слой
        polygon_layer = CustomDEMPlugin.add_polygon_to_layer(polygon)
        
        # 7. Обрезаем DEM с использованием выбранного полигона
        CustomDEMPlugin.clip_dem_with_polygon(dem_layer, polygon_layer, masked_dem_output_path)

    # Инициализация сбора точек
    def start_point_collection():
        
        collector = CustomDEMPlugin.PointCollector(iface.mapCanvas())
        iface.mapCanvas().setMapTool(collector)
        print("Щелкните по карте, чтобы выбрать точки.")
        
        return collector
    '''
    ======================= CREATING FOREST BELT===========================
    '''
    def add_dem_layer(output_path):
        # Добавить скачанный слой DEM в проект QGIS
        dem_layer = QgsRasterLayer(output_path, "SRTM DEM Layer")
        if not dem_layer.isValid():
            print(f"Ошибка: Файл {output_path} недоступен или поврежден.")
        QgsProject.instance().addMapLayer(dem_layer)
        return

    def reproject_dem2():
        # Репроекция DEM из EPSG:4326 в EPSG:3857
        output_reprojected_path =  os.path.join(CustomDEMPlugin.project_folder, "reprojected_dem.tif")
        output_path =  os.path.join(CustomDEMPlugin.project_folder, "masked_dem.tif")
        reprojected_dem = processing.run("gdal:warpreproject", {
            'INPUT': output_path,
            'TARGET_CRS': QgsCoordinateReferenceSystem('EPSG:3857'),
            'RESAMPLING': 0,
            'NODATA': -9999,
            'TARGET_RESOLUTION': 30,
            'OPTIONS': '',
            'DATA_TYPE': 0,
            'OUTPUT': output_reprojected_path
        })['OUTPUT']
        print(f"Репроекция выполнена. Файл сохранен в {output_reprojected_path}")

        return reprojected_dem

    def load_dem_to_numpy():
        output_path =  os.path.join(CustomDEMPlugin.project_folder, "masked_dem.tif")
        # Загрузка DEM в numpy массив для анализа
        dem_raster = gdal.Open(output_path)
        dem_band = dem_raster.GetRasterBand(1)
        dem_data = dem_band.ReadAsArray()
        return dem_data, dem_raster

    def setting_dem_coordinates(dem_data, dem_raster):
        # Находим максимальную и минимальную высоту
        max_height = np.max(dem_data)
        min_height = np.min(dem_data)

        # Координаты точек с максимальной и минимальной высотой
        max_coords = np.unravel_index(np.argmax(dem_data), dem_data.shape)
        min_coords = np.unravel_index(np.argmin(dem_data), dem_data.shape)

        # Преобразуем индексы пикселей в географические координаты (EPSG:4326)
        transform = dem_raster.GetGeoTransform()
        max_x_4326 = transform[0] + max_coords[1] * transform[1] + max_coords[0] * transform[2]
        max_y_4326 = transform[3] + max_coords[0] * transform[4] + max_coords[1] * transform[5]

        min_x_4326 = transform[0] + min_coords[1] * transform[1] + min_coords[0] * transform[2]
        min_y_4326 = transform[3] + min_coords[0] * transform[4] + min_coords[1] * transform[5]

        transformer_to_3857 = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)

        # Преобразование координат точек с максимальной и минимальной высотой в EPSG:3857
        max_x_3857, max_y_3857 = transformer_to_3857.transform(max_x_4326, max_y_4326)
        min_x_3857, min_y_3857 = transformer_to_3857.transform(min_x_4326, min_y_4326)
        coordinates = [
            (max_x_3857, max_y_3857),
            (min_x_3857, min_y_3857),
        ]
        return coordinates, min_height, max_height

    def create_temp_vector_layer():
        # Создаем временный векторный слой для точек
        layer = QgsVectorLayer("Point?crs=EPSG:3857", "points1", "memory")
        QgsProject.instance().addMapLayer(layer)
        return layer

    def set_attribute_fields(layer):
        # Добавляем поля для атрибутов (опционально)
        fields = QgsFields()
        fields.append(QgsField("ID", QVariant.Int))

        layer.dataProvider().addAttributes(fields)
        layer.updateFields()
        return layer

    def add_points(coordinates, layer):
        features = []
        for i, coord in enumerate(coordinates, start=1):
            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(coord[0], coord[1])))
            feature.setAttributes([i])  # ID точки
            features.append(feature)

        layer.dataProvider().addFeatures(features)
        layer.updateExtents()

        print("Точки успешно добавлены!")
        return

    def create_points():
        output_path =  os.path.join(CustomDEMPlugin.project_folder, "masked_dem.tif")  # Путь к выходному файлу после обрезки
        CustomDEMPlugin.add_dem_layer(output_path)
        reprojected_dem_mask = CustomDEMPlugin.reproject_dem2()
        dem_data, dem_raster = CustomDEMPlugin.load_dem_to_numpy()
        coordinates, min_height, max_height = CustomDEMPlugin.setting_dem_coordinates(dem_data, dem_raster)
        layer = CustomDEMPlugin.create_temp_vector_layer()
        layer = CustomDEMPlugin.set_attribute_fields(layer)
        CustomDEMPlugin.add_points(coordinates, layer)
        return reprojected_dem_mask, min_height, max_height


    def calculate(H, J, angle):
        # Расчёты
        L = H * J  # Идеальное расстояние между лесополосами
        hop = L * math.tan(math.radians(angle))  # Шаг по высоте
        print(f"Идеальное расстояние L: {L}")
        print(f"Шаг по высоте hop: {hop}")

        return L, hop

    def construct_isolines(reprojected_dem_mask, hop, max_height):
        # Построение изолиний от max_z до min_z
        contours_output_path =  os.path.join(CustomDEMPlugin.project_folder, "contours_output.shp")  # Укажите путь для сохранения изолиний

        try:
            result = processing.run("gdal:contour", {
                'INPUT': reprojected_dem_mask,
                'BAND': 1,
                'INTERVAL': hop,
                'FIELD_NAME': 'ELEV',
                'BASE': max_height,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            print(f"Изолинии успешно созданы: {result}")
        except Exception as e:
            print(f"Ошибка при создании изолиний: {e}")

        return contours_output_path, result

    def add_isolines_to_a_layer(contours_output_path, result):
        # Проверка, создан ли временный файл
        contours_output_path = result['OUTPUT']
        print(f"Временный файл изолиний создан: {contours_output_path}")

        if os.path.getsize(contours_output_path) == 0:
            print("Ошибка: Файл изолиний пуст.")

        # Загрузка изолиний в слой
        contours_layer = QgsVectorLayer(contours_output_path, 'Contours', 'ogr')

        print(f"CRS слоя: {contours_layer.crs().authid()}")
        print(f"CRS проекта: {QgsProject.instance().crs().authid()}")


        if not contours_layer.isValid():
            raise Exception("Не удалось загрузить слой изолиний.")
        QgsProject.instance().addMapLayer(contours_layer)

        return contours_layer

    def filter_isoline(contours_layer):
        # Фильтрация изолиний по диапазону высот
        filtered_layer = QgsVectorLayer("LineString?crs=EPSG:3857", "Filtered Contours", "memory")  # Используем ту же CRS, что и DEM
        filtered_provider = filtered_layer.dataProvider()
        filtered_provider.addAttributes(contours_layer.fields())  # Копируем атрибуты из изолиний
        filtered_layer.updateFields()
        return filtered_provider, filtered_layer

    def adding_isolines_by_height(contours_layer, min_height, max_height, filtered_provider, filtered_layer):
        # Добавляем только изолинии в диапазоне высот
        for feature in contours_layer.getFeatures():
            elevation = feature['ELEV']
            if min_height <= elevation <= max_height:  # Диапазон высот
                filtered_provider.addFeatures([feature])  # Добавляем отфильтрованные изолинии

        filtered_layer.updateExtents()  # Обновляем границы слоя
        QgsProject.instance().addMapLayer(filtered_layer)
        return

    def create_isolines(reprojected_dem_mask, min_height, max_height):
        # Параметры задачи
        H = 15  # Высота лесополосы
        J = 20  # Коэффициент влияния
        angle = 3  # Угол наклона в градусах

        L, hop = CustomDEMPlugin.calculate(H, J, angle)
        contours_output_path, result = CustomDEMPlugin.construct_isolines(reprojected_dem_mask, hop, max_height)
        contours_layer = CustomDEMPlugin.add_isolines_to_a_layer(contours_output_path, result)
        filtered_provider, filtered_layer = CustomDEMPlugin.filter_isoline(contours_layer)
        CustomDEMPlugin.adding_isolines_by_height(contours_layer, min_height, max_height, filtered_provider, filtered_layer)
        return filtered_layer

    def add_forests_layer():
        # Создание слоя для лесополос
        forest_layer = QgsVectorLayer("LineString?crs=EPSG:3857", "Forest Belts", "memory")  # Совместимый CRS
        forest_provider = forest_layer.dataProvider()
        forest_provider.addAttributes([QgsField("Step", QVariant.Int)])  # Добавляем поле Step
        forest_layer.updateFields()

        return forest_layer, forest_provider

    # Генерация цвета
    def generate_shades(base_color, steps):
        shades = []
        for i in range(steps):
            factor = i / (steps - 1)  # Нормализуем в диапазон [0, 1]
                
            # Увеличиваем интенсивность цвета для яркости
            r = int(base_color.red() * (1 - factor) + 255 * factor)  # Плавное увеличение от base к яркому
            g = int(base_color.green() * (1 - factor) + 255 * factor)
            b = int(base_color.blue() * (1 - factor) + 255 * factor)
            
            shades.append(QColor(r, g, b))
        return shades

    def generate_color_pallete():
        # Базовый цвет (чистый красный)
        base_color = QColor(255, 0, 0)
        # Базовый цвет (чистый зеленый)
        base_color1 = QColor(0, 255, 0)
        # Базовый цвет (чистый синий)
        base_color2 = QColor(0, 0, 255)

        grad_steps = 255

        # Генерируем оттенки
        colors = CustomDEMPlugin.generate_shades(base_color2, grad_steps) + CustomDEMPlugin.generate_shades(base_color1, grad_steps) + CustomDEMPlugin.generate_shades(base_color, grad_steps)  
        return colors

    def add_forest_feature(filtered_layer, forest_provider,forest_layer,  colors):
        # Добавление лесополос с градиентом цветов
        step_index = 1

        categories = []  # Список категорий для рендера
        # Добавление лесополос
        for feature in filtered_layer.getFeatures():
            geometry = feature.geometry()
            if not geometry.isEmpty():  # Проверяем, что геометрия не пустая
                print(f"Feature {step_index}: Geometry is empty = {geometry.isEmpty()}")

                forest_feature = QgsFeature()
                forest_feature.setGeometry(geometry)
                forest_feature.setAttributes([step_index])  # Присваиваем шаг
                forest_provider.addFeatures([forest_feature])
                
                # Создаем символ с градиентным цветом
                color = colors[step_index % len(colors)]
                symbol = QgsSymbol.defaultSymbol(forest_layer.geometryType())
                symbol.setColor(color)

                # Добавляем категорию для рендера
                category = QgsRendererCategory(step_index, symbol, f"Лесополоса {step_index}")
                categories.append(category)

                
                step_index += 1
        return categories

    def config_render(forest_layer, categories):
        # Настраиваем рендерер для слоя
        renderer = QgsCategorizedSymbolRenderer('Step', categories)
        forest_layer.setRenderer(renderer)

        forest_layer.updateExtents()  # Обновляем границы слоя
        QgsProject.instance().addMapLayer(forest_layer)
        return 

    def check_forest_layers():
        # Получение слоев
        forest_layer = QgsProject.instance().mapLayersByName('Forest Belts')[0]
        selected_region_layer = QgsProject.instance().mapLayersByName('Selected Region')[0]
        
        # Проверка наличия слоев
        if not forest_layer or not selected_region_layer:
            print("Не найдены слои 'Forest Belts' или 'Selected Region'")
            exit()
        return forest_layer, selected_region_layer

    def create_boundary_layer(selected_region_layer):
        # Создание слоя границ для замыкания
        boundary_result = processing.run("native:boundary", {
            'INPUT': selected_region_layer,
            'OUTPUT': 'memory:'
        })
        boundary_layer = boundary_result['OUTPUT']
        return boundary_layer

    def setting_up_render(forest_layer):
        # Проверяем наличие поля 'Step' в слое лесополос
        if 'Step' not in [field.name() for field in forest_layer.fields()]:
            forest_layer.dataProvider().addAttributes([QgsField('Step', QVariant.Int)])
            forest_layer.updateFields()

        # Подготовка для рендеринга
        categories = []
        step_index = 0

        # Уникальные шаги (STEPS)
        unique_steps = sorted(set(f['Step'] for f in forest_layer.getFeatures()))
        return categories, step_index, unique_steps

    def process_step(unique_steps, forest_layer, boundary_layer, colors, categories, step_index):

        # Основная обработка шагов
        for step in unique_steps:
            print(f"Обработка шага {step}")
            
            step_features = [f for f in forest_layer.getFeatures() if f['Step'] == step]
            
            for feature in step_features:
                geometry = feature.geometry()
                if geometry.isEmpty():
                    print(f"Пропуск пустой геометрии на шаге {step}")
                    continue
                
                # Поиск ближайшего контура
                shortest_distance = float('inf')
                best_contour = None
                
                for boundary_feature in boundary_layer.getFeatures():
                    boundary_geom = boundary_feature.geometry()
                    distance = geometry.distance(boundary_geom)
                    if distance < shortest_distance:
                        shortest_distance = distance
                        best_contour = boundary_geom

                if best_contour:
                    # Создание новой замкнутой геометрии
                    closed_geometry = geometry.combine(best_contour)
                    new_feature = QgsFeature(forest_layer.fields())
                    new_feature.setGeometry(closed_geometry)
                    new_feature.setAttributes(feature.attributes())
                    
                    forest_layer.dataProvider().addFeatures([new_feature])
                    
                    # Создание символа для рендеринга
                    color = colors[step_index % len(colors)]
                    symbol = QgsSymbol.defaultSymbol(forest_layer.geometryType())
                    symbol.setColor(color)
                    
                    category = QgsRendererCategory(step, symbol, f"Лесополоса {step}")
                    categories.append(category)

                step_index += 1

        return forest_layer

    def render_forest_belts(categories, forest_layer):

        # Настройка рендера
        renderer = QgsCategorizedSymbolRenderer('Step', categories)
        forest_layer.setRenderer(renderer)
        forest_layer.updateExtents()  # Обновление слоя
        QgsProject.instance().addMapLayer(forest_layer)


    def generate_forest_belts_layer(filtered_layer,):
        forest_layer, forest_provider = CustomDEMPlugin.add_forests_layer()
        colors = CustomDEMPlugin.generate_color_pallete()
        categories = CustomDEMPlugin.add_forest_feature(filtered_layer, forest_provider,forest_layer, colors)
        CustomDEMPlugin.config_render(forest_layer, categories)
        forest_layer, selected_region_layer = CustomDEMPlugin.check_forest_layers()
        boundary_layer = CustomDEMPlugin.create_boundary_layer(selected_region_layer)
        categories, step_index, unique_steps = CustomDEMPlugin.setting_up_render(forest_layer)
        base_color = QColor(0, 255, 0)
        colors = CustomDEMPlugin.generate_shades(base_color, 255)
        forest_layer = CustomDEMPlugin.process_step(unique_steps, forest_layer, boundary_layer, colors, categories, step_index)
        CustomDEMPlugin.render_forest_belts(categories, forest_layer)

        return

    def create_forest_belts():

        reprojected_dem_mask, min_height, max_height = CustomDEMPlugin.create_points() 
        filtered_layer = CustomDEMPlugin.create_isolines(reprojected_dem_mask, min_height, max_height)
        CustomDEMPlugin.generate_forest_belts_layer(filtered_layer)
        print("Лесополосы успешно замкнуты и добавлены в проект.")

        return
    
    
    def show_layer_visibility_dialog():

        # Создать диалоговое окно
        dialog = QDialog()
        dialog.setWindowTitle("Выбор слоев")
        layout = QVBoxLayout()

        # Добавить лейбл
        label = QLabel("Выберите слои для отображения:")
        layout.addWidget(label)

        # Получить доступ к дереву слоев проекта
        root = QgsProject.instance().layerTreeRoot()

        # Создать чекбокс для каждого слоя
        checkboxes = {}
        for layer in QgsProject.instance().mapLayers().values():
            layer_tree_node = root.findLayer(layer.id())
            if layer_tree_node:  # Проверка наличия слоя в дереве
                checkbox = QCheckBox(layer.name())
                checkbox.setChecked(layer_tree_node.isVisible())  # Получить настоящую видимость
                layout.addWidget(checkbox)
                checkboxes[layer_tree_node] = checkbox

        # Добавить кнопку 
        apply_button = QPushButton("Применить")
        layout.addWidget(apply_button)

        def apply_layer_visibility():
            for layer_tree_node, checkbox in checkboxes.items():
                layer_tree_node.setItemVisibilityChecked(checkbox.isChecked())
            dialog.close()

        # Соединить кнопку подтверждения с функцией
        apply_button.clicked.connect(apply_layer_visibility)

        # Настройка макета и отображение диалогового окна
        dialog.setLayout(layout)
        dialog.exec_()


    def forest():

        CustomDEMPlugin.get_main_def()

        main_dem_file_path = os.path.join(CustomDEMPlugin.project_folder, "srtm_output.tif")  # Путь к вашему DEM файлу
        masked_dem_output_path = os.path.join(CustomDEMPlugin.project_folder, "masked_dem.tif")  # Путь к выходному файлу после обрезки

        CustomDEMPlugin.process_dem_with_polygon(main_dem_file_path, masked_dem_output_path)
        CustomDEMPlugin.create_forest_belts()

        return


    # Определите основную функцию для диалога
    def show_choice_dialog():
        # Создание диалогового окна
        dialog = QDialog()
        dialog.setWindowTitle("Выбор функции")
        layout = QVBoxLayout()

        # Добавление метки
        label = QLabel("Что вы хотите сделать?")
        layout.addWidget(label)

        # Добавляйте кнопки для различных вариантов
        waterlines_button = QPushButton("Создать речную сеть")
        forest_belts_button = QPushButton("Создать лесополосы")

        layout.addWidget(waterlines_button)
        layout.addWidget(forest_belts_button)

        # Определение действий для кнопок
        def create_waterlines():
            dialog.close()
            CustomDEMPlugin.river()

        def create_forest_belts():
            dialog.close()
            CustomDEMPlugin.forest()

        # Свяжите кнопки с их действиями
        waterlines_button.clicked.connect(create_waterlines)
        forest_belts_button.clicked.connect(create_forest_belts)

        # Настройка макета и отображение диалогового окна
        dialog.setLayout(layout)
        dialog.exec_()

    def clear_cache():
        project = QgsProject.instance()
        # Перебор всеч слоев в проекте
        for layer in project.mapLayers().values():
            # Проверка, содержит ли имя слоя слово "buffer" 
            if "buffer" in layer.name().lower():
                # Удалить слой из проекта
                project.removeMapLayer(layer)

    def prepare():
        project = QgsProject.instance()
        # Удалить все слои
        for layer in list(project.mapLayers().values()): 
            project.removeMapLayer(layer)

        # Удалить определенные форматы файлов (e.g., shapefiles, GeoTIFFs, etc.)
        for file_pattern in ["*.shp", "*.shx", "*.dbf", "*.prj", "*.tif"]:
            for file_path in glob.glob(os.path.join(CustomDEMPlugin.project_folder, file_pattern)):
                try:
                    os.remove(file_path)
                    print(f"Deleted: {file_path}")
                except Exception as e:
                    print(f"Error deleting {file_path}: {e}")
                    
        # Очистка кэша холста карты
        iface.mapCanvas().refreshAllLayers()

        # Очистка кэша рендеринга
        QgsProject.instance().reloadAllLayers()
        return

    def run_programm():
        #Подготовка к работе
        CustomDEMPlugin.clear_cache()
        CustomDEMPlugin.prepare()
        
        #Запуск диалогового окна
        CustomDEMPlugin.show_choice_dialog()
        CustomDEMPlugin.show_layer_visibility_dialog()
        
        return

    
