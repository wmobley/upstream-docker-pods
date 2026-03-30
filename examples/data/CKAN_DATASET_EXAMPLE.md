# Upstream Example Measurements and Sensors

## Dataset

**Title**  
Upstream Example Measurements and Sensors

**URL**  
https://ckan.tacc.utexas.edu/dataset/upstream-example-measurements-and-sensors

**Description**  
Example Upstream station export containing time-series measurements and the corresponding sensor definitions.

This dataset includes:

- `measurements.csv` with 8,961 measurement records
- `sensors.csv` with 3 sensor definitions
- Temporal coverage from **03/01/2025** to **06/02/2025**
- Spatial coverage for a single station near latitude `30.18611`, longitude `-93.90833`
- Upload API requirement: both `upload_file_sensors` and `upload_file_measurements` are mandatory in the same request

**Tags**  
upstream, example-data, measurements, sensors, hydrology, csv

**License**  
TBD

License definitions and additional information can be found at http://opendefinition.org/

**Organization**  
upstream

**Visibility**  
Private

**Source**  
./upstream-docker-pods/examples/data/

**Version**  
1.0

**Author**  
Upstream Team

**Author Email**  
TBD

**Maintainer**  
Upstream Team

**Maintainer Email**  
TBD

**Temporal Coverage Start**  
03/01/2025

**Temporal Coverage End**  
06/02/2025

**Spatial Coverage**  
```json
{"type":"Point","coordinates":[-93.90833,30.18611]}
```

## Resources

### Resource 1

**URL**  
./upstream-docker-pods/examples/data/measurements.csv

**Name**  
Measurements CSV

**Description**  
Time-series measurement export for the example station.

For API upload compatibility:

- Required columns: `collectiontime`, `Lon_deg`, `Lat_deg`
- Required dynamic columns: one measurement column for each sensor `alias` defined in `sensors.csv`
- Optional columns: any additional columns are ignored by the current importer
- The current uploader does not use fields such as `Reading`, `Receive`, `Value`, `Unit`, or `Data Quality`
- Sensor alias column names must match the `alias` values in `sensors.csv` exactly
- Empty measurement cells are allowed and skipped
- `Lon_deg` and `Lat_deg` are used to build the geometry stored for each measurement

**Format**  
CSV

**MINT Standard Variables**  
TBD

### Resource 2

**URL**  
./upstream-docker-pods/examples/data/sensors.csv

**Name**  
Sensors CSV

**Description**  
Sensor metadata for the example station.

For API upload compatibility:

- Required column: `alias`
- Optional supported columns: `description`, `postprocess`, `postprocessscript`, `units`, `variablename`, `metadata`
- The importer actively uses `alias`, `variablename`, `units`, `postprocess`, and `postprocessscript`
- If `variablename` is missing, the API defaults it to `No BestGuess Formula`
- `description` is accepted by the schema, but this CSV importer does not currently persist it during upload
- `metadata` is accepted by the schema, but this CSV importer does not currently persist it during upload
- `BestGuessFormula` is not the API field name; use `variablename` instead
- `datatype` is not used by the current CSV upload importer

**Format**  
CSV

**MINT Standard Variables**  
TBD
