from qgis.core import QgsProject, QgsCoordinateReferenceSystem, QgsPointXY, QgsRasterLayer, QgsVectorLayer, QgsGeometry, \
    QgsField
from qgis.core import (
    QgsProject,
    QgsSpatialIndex,
    QgsFeatureRequest,
    QgsVectorLayer,
    QgsGeometry
)
from qgis.analysis import QgsNativeAlgorithms
from processing_saga_nextgen.saga_nextgen_plugin import SagaNextGenAlgorithmProvider
from qgis.PyQt.QtCore import QVariant
import requests
import os
from pyproj import Transformer
import processing

# Папка для проекта
project_folder = '/Users/mbp-15/Desktop/'

# Установить систему координат проекта (EPSG:3857 - Pseudo-Mercator)
crs = QgsCoordinateReferenceSystem("EPSG:3857")
QgsProject.instance().setCrs(crs)

# Включить встроенные алгоритмы обработки QGIS
QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())

# Добавить слой OpenTopoMap
opentopo_url = 'type=xyz&zmin=0&zmax=21&url=https://tile.opentopomap.org/{z}/{x}/{y}.png'
opentopo_layer = QgsRasterLayer(opentopo_url, 'OpenTopoMap', 'wms')
QgsProject.instance().addMapLayer(opentopo_layer)

# Координаты озера в системе координат EPSG:3857
x_3857, y_3857 = 4316873, 7711643

# Преобразовать координаты в широту и долготу (EPSG:4326)
transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
longitude, latitude = transformer.transform(x_3857, y_3857)

# Определить bounding box вокруг точки с радиусом 0.5 градуса широты и долготы
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
output_path = f'{project_folder}srtm_output.tif'
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

# Загрузка алгоритмов SAGA
provider = SagaNextGenAlgorithmProvider()
provider.loadAlgorithms()
QgsApplication.processingRegistry().addProvider(provider=provider)

# Использовать SAGA Fill Sinks для извлечения водосборов
filled_relief = processing.run("sagang:fillsinkswangliu", {
    'ELEV': reprojected_relief, 'FILLED': 'TEMPORARY_OUTPUT',
    'FDIR': 'TEMPORARY_OUTPUT', 'WSHED': f'{project_folder}basins.sdat',
    'MINSLOPE': 0.01})['WSHED']

# Сохранить и добавить заполненные области водосбора в проект
basins = QgsRasterLayer(f'{project_folder}basins.sdat', 'basins')
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
merge_result = processing.run("native:multiparttosingleparts", {'INPUT': merge_result, 'OUTPUT': f'{project_folder}merge_result.gpkg'})['OUTPUT']

# Добавить объединенный слой в проект
rivers_merged = QgsVectorLayer(f'{project_folder}merge_result.gpkg', 'rivers_merged')
QgsProject.instance().addMapLayer(rivers_merged)

# Загрузить полигональные данные о водных объектах
query = processing.run('quickosm:buildqueryextent', {
    'KEY': 'natural', 'VALUE': 'water', 'EXTENT': bbox, 'TIMEOUT': 25})
file = processing.run("native:filedownloader", {
    'URL': query['OUTPUT_URL'], 'OUTPUT': f'{project_folder}water.gpkg'})['OUTPUT']
water = iface.addVectorLayer(file + '|layername=multipolygons', "water", "ogr")

# Рассчитать координаты начальных и конечных точек линий
start_x = processing.run("native:fieldcalculator", {
    'INPUT': f'{project_folder}merge_result.gpkg', 'FIELD_NAME': 'start_x',
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
    'OUTPUT': f'{project_folder}rivers_with_points.gpkg'})['OUTPUT']

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


# Начать редактирование слоя точек и создать точки максимальной высоты для каждой линии
pointLayer.startEditing()
for feature in layer.getFeatures():
    # Создание точек на основании высотных данных
    if feature['max_z'] != None:
        if feature['start_x'] != None and feature['start_y'] != None and feature['start_z'] != None and feature['start_z'] == feature['max_z']:
            point = QgsPointXY(feature['start_x'], feature['start_y'])
            new_feature = QgsFeature()
            new_feature.setFields(fields)
            new_feature.setGeometry(QgsGeometry.fromPointXY(point))
            new_feature['x'] = feature['start_x']
            new_feature['y'] = feature['start_y']
            new_feature['z'] = feature['start_z']
            pointLayer.addFeature(new_feature)

        elif feature['end_x'] != None and feature['end_y'] != None and feature['end_z'] != None and feature['end_z'] == feature['max_z']:
            point = QgsPointXY(feature['end_x'], feature['end_y'])
            new_feature = QgsFeature()
            new_feature.setFields(fields)
            new_feature.setGeometry(QgsGeometry.fromPointXY(point))
            new_feature['x'] = feature['end_x']
            new_feature['y'] = feature['end_y']
            new_feature['z'] = feature['end_z']
            pointLayer.addFeature(new_feature)
# Завершение редактирования и сохранение изменений
pointLayer.commitChanges(True)

isolines = processing.run("gdal:contour",
                          {'INPUT': reprojected_relief, 'BAND': 1, 'INTERVAL': 18, 'FIELD_NAME': 'ELEV',
                           'CREATE_3D': False, 'IGNORE_NODATA': False, 'NODATA': None, 'OFFSET': 0, 'EXTRA': '',
                           'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']
isolines = processing.run("native:multiparttosingleparts", {'INPUT': isolines, 'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']
QgsProject.instance().addMapLayer(isolines)




#БЛИЖАЙШИЕ ИЗОЛИНИИ:
point_layer = QgsProject.instance().mapLayersByName('MaxHeightPoints')[0]
contour_layer = QgsProject.instance().mapLayersByName('Single parts')[0]

# Создание нового слоя для ближайших изолиний
crs = contour_layer.crs().toWkt()
new_layer = QgsVectorLayer(f"LineString?crs={crs}", "Ближайшие изолинии", "memory")
new_layer.dataProvider().addAttributes(contour_layer.fields())
new_layer.updateFields()

# Индекс поля ELEV в слое изолиний
elev_index = contour_layer.fields().indexOf('ELEV')
z_index = point_layer.fields().indexOf('z')

# Множество для хранения ID ближайших изолиний
nearest_isoline_ids = set()

# Поиск ближайших изолиний
for point_feature in point_layer.getFeatures():
    point_z = point_feature['z']

    min_difference = float('inf')
    nearest_isoline_id = None
    
    for contour_feature in contour_layer.getFeatures():
        contour_elev = contour_feature['ELEV']
        difference = abs(point_z - contour_elev)

        if difference < min_difference:
            min_difference = difference
            nearest_isoline_id = contour_feature.id()

    if nearest_isoline_id is not None:
        nearest_isoline_ids.add(nearest_isoline_id)

# Добавление ближайших изолиний в новый слой
new_layer.startEditing()
for contour_feature in contour_layer.getFeatures():
    if contour_feature.id() in nearest_isoline_ids:
        new_feature = QgsFeature(contour_feature)
        new_feature.setGeometry(QgsGeometry(contour_feature))
        new_layer.addFeature(new_feature)

new_layer.commitChanges()

# Добавление нового слоя в проект
QgsProject.instance().addMapLayer(new_layer)