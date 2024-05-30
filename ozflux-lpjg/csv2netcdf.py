#!/usr/bin/env python
#
# Convert a csv file to netcdf format.
#

import math, traceback, pandas, xarray

from ozflux_common import VERSION
from ozflux_logging import *
from ozflux_netcdf import *

from argparse import ArgumentParser
from sys import argv
from netCDF4 import Dataset, date2num

# Default name of the latitude dimension in the output file.
DIM_LAT = "lat"

# Default name of the longitude dimension in the output file.
DIM_LON = "lon"

# Default name of the time dimension in the output file.
DIM_TIME = "time"

# Units used in the latitude variable.
UNITS_LAT = "degrees_north"

# Units used in the longitude variable.
UNITS_LON = "degrees_east"

# Units used in the time variable.
TIME_UNITS = "hours since 1900-01-01"

# Calendar used in the time variable.
TIME_CALENDAR = "gregorian"

class Options:
    """
    Class for storing CLI arguments from the user.

    @param log: Log level.
    @param in_file: Input file.
    @param out: Output file.
    @param prog: True to write progress messages, 0 otherwise.
    @param metadata_line: Character which defines a metadata line.
    @param metadata_delimiter: Character which separates metadata names/values.
    @param time_column: Name of the time column.
    @param time_fmt: Format of data in the time column. E.g. %d/%m/%y %H:%M:%S).
    @param latitude: Latitude of all data in the file.
    @param latitude_column: Name of the latitude column.
    @param longitude: Longitude of all data in the file.
    @param longitude_column: Name of the longitude column.
    @param chunk_sizes: Chunk sizes to be used in the output file.
    @param compression_level: zlib deflation level to be used in the output file. 0 means no compression.
    @param missing_value: Missing value used in input file.
    """
    def __init__(self, log : LogLevel, in_file: str, out_file: str, prog: bool
                 , time_column: str, time_fmt: str, latitude: float
                 , latitude_column: str, longitude: float
                 , longitude_column: str, dim_lat: str, dim_lon: str
                 , dim_time: str, chunk_sizes: list[tuple[str, int]]
                 , compression_level: int, missing_value: int):

        self.log_level = log
        self.report_progress = prog

        self.in_file = in_file
        self.out_file = out_file

        self.time_column = time_column
        self.time_fmt = time_fmt

        self.latitude = latitude
        self.latitude_column = latitude_column
        self.longitude = longitude
        self.longitude_column = longitude_column

        self.dim_lat = dim_lat
        self.dim_lon = dim_lon
        self.dim_time = dim_time
        self.chunk_sizes = chunk_sizes

        self.missing_value = missing_value

        self.compression_level = compression_level
        if compression_level < 0:
            raise ValueError(f"Invalid compression level (must be >= 0): {compression_level}")

def parse_args(argv: list[str]) -> Options:
    """
    Parse CLI arguments, return a parsed options object.

    @param argv: Raw CLI arguments.

    @return Parsed Options object.
    """
    parser = ArgumentParser(prog=argv[0], description = "Convert a csv file to netcdf format")
    parser.add_argument("-v", "--verbosity", type = int, help = "Logging verbosity (1-5, default 3)", nargs = "?", const = LogLevel.INFORMATION, default = LogLevel.INFORMATION)
    parser.add_argument("-i", "--in-file", required = True, help = "Input .csv file to be processed")
    parser.add_argument("-o", "--out-file", required = True, help = "Path to the output file.")
    parser.add_argument("-p", "--show-progress", action = "store_true", help = "Report progress")
    # parser.add_argument("--metadata-line", help = "Character which defines a metadata line. Any lines at the start of the file which start with this character will be treated as metadata lines")
    # parser.add_argument("--metadata-delimiter", help = "Character which separates metadata names from their associated values on metadata lines as defined by the --metadata-delimiter option")
    parser.add_argument("--version", action = "version", version = "%(prog)s " + VERSION)
    parser.add_argument("--time-column", required = True, help = "Name of the time column")
    parser.add_argument("--time-format", required = True, help = r"Format of data in the time column. E.g. %d/%m/%y %H:%M:%S).")
    parser.add_argument("--missing-value", help = "Special value used in input file to represent missing values.")

    parser.add_argument("--dim-lat", default = DIM_LAT, help = f"Optional name of the latitude dimension to be created in the output file (default: {DIM_LAT})")
    parser.add_argument("--dim-lon", default = DIM_LON, help = f"Optional name of the longitude dimension to be created in the output file (default: {DIM_LON})")
    parser.add_argument("--dim-time", default = DIM_TIME, help = f"Optional name of the time dimension to be created in the output file (default: {DIM_TIME})")
    parser.add_argument("-c", "--chunk-sizes", default = "", help = "Chunk sizes for each dimension. This is optional, and if omitted, the size of each dimension will be used. This should be specified in the same format as for nco. E.g. lat/1,lon/1,time/365")
    parser.add_argument("--compression-level", type = int, default = 0, help = "Compression level 0-9. 0 means no compression. 9 means highest compression ratio but slowest performance (default: 0).")

    group_lat = parser.add_mutually_exclusive_group(required = True)
    group_lat.add_argument("--latitude", type = float, help = "Latitude of all rows in the file")
    group_lat.add_argument("--latitude-column", help = "Name of the column containing latitude data")

    group_lon = parser.add_mutually_exclusive_group(required = True)
    group_lon.add_argument("--longitude", type = float, help = "Longitude of all rows in the file")
    group_lon.add_argument("--longitude-column", help = "Name of the column containing longitude data")

    p = parser.parse_args(argv[1:])

    chunk_sizes = parse_chunksizes(p.chunk_sizes)

    return Options(p.verbosity, p.in_file, p.out_file, p.show_progress
                   , p.time_column, p.time_format, p.latitude, p.latitude_column
                   , p.longitude, p.longitude_column, p.dim_lat, p.dim_lon
                   , p.dim_time, chunk_sizes, p.compression_level
                   , p.missing_value)#, p.metadata_line, p.metadata_delimiter)

def read_input_file(opts: Options) -> pandas.DataFrame:
    """
    Read the input file and return it as a dataframe with dates parsed, lat/lon
    columns existing (with names stored in opts).

    @param opts: Parsing options.
    """
    data = pandas.read_csv(opts.in_file, na_values = opts.missing_value)

    if opts.latitude_column is None:
        log_debug(f"Latitude column not specified. Using constant latitude: {opts.latitude}")
        if opts.latitude < -90 or opts.latitude > 90:
            raise ValueError(f"Invalid latitude: {opts.latitude}")
        data[DIM_LAT] = opts.latitude
        opts.latitude_column = DIM_LAT

    if opts.longitude_column is None:
        log_debug(f"Longitude column not specified. Using constant longitude: {opts.latitude}")
        if opts.longitude < -180 or opts.longitude > 180:
            raise ValueError(f"Invalid longitude: {opts.longitude}")
        data[DIM_LON] = opts.longitude
        opts.longitude_column = DIM_LON

    data = data.rename(columns = {
        opts.longitude_column: opts.dim_lon,
        opts.latitude_column: opts.dim_lat,
        opts.time_column: opts.dim_time,
    })

    # Convert time column to datetime type.
    # data[opts.time_column] = [datetime.datetime.strptime(t.__str__(), opts.time_fmt) for t in data[opts.time_column]]
    log_debug("Parsing dates from input file")
    # data[opts.dim_time] = data[opts.dim_time].apply(lambda x: datetime.datetime.strptime(str(x), opts.time_fmt))
    data[opts.dim_time] = pandas.to_datetime(data[opts.dim_time], format = opts.time_fmt)
    # data[opts.dim_time] = data[opts.dim_time].apply(lambda x: x.date())
    data[opts.dim_time] = date2num(list(data[opts.dim_time]), TIME_UNITS, TIME_CALENDAR)
    log_debug("Successfully parsed dates from input file")
    return data

def sort_data(data: list[float]) -> list[float]:
    """
    Return all unique values in the given list, in ascending order.
    """
    result = list(set(data))
    result.sort()
    return result

def create_coordinate(opts: Options, data, nc: Dataset
    , name: str, units: str, std_name: str, long_name: str):
    """
    Create coordinate in the output file.
    """
    # Sort data to ensure the variable is monotonic.
    data = data[name]
    data = sort_data(data)

    # Create dimension.
    create_dim_if_not_exists(nc, name, len(data))
    dim = nc.dimensions[name]

    # Get chunk size for this dimension.
    chunk_size = try_get_chunk_size(name, nc.dimensions[name].size, opts.chunk_sizes)

    # Create variable.
    create_var_if_not_exists(nc, name, FORMAT_FLOAT, (name,)
                             , opts.compression_level, COMPRESSION_ZLIB
                             , chunksizes = (chunk_size,))
    var = nc.variables[name]

    # Write data to the file in chunks.
    for i in range(0, dim.size, chunk_size):
        lower = i
        upper = min(dim.size, i + chunk_size)
        var[lower:upper] = data[lower:upper]

    # Write metadata.
    setattr(var, ATTR_STD_NAME, std_name)
    setattr(var, ATTR_LONG_NAME, long_name)
    setattr(var, ATTR_UNITS, units)

def init_outfile(opts: Options, data: pandas.DataFrame, nc: Dataset):
    """
    Initialise the output file.
    """
    # Create coordinate variables/dimensions.
    create_coordinate(opts, data, nc, opts.dim_lat, UNITS_LAT, STD_LAT, LONG_LAT)
    create_coordinate(opts, data, nc, opts.dim_lon, UNITS_LON, STD_LON, LONG_LON)
    create_coordinate(opts, data, nc, opts.dim_time, TIME_UNITS, STD_TIME, LONG_TIME)

    # Write calendar attribute.
    setattr(nc.variables[opts.dim_time], ATTR_CALENDAR, TIME_CALENDAR)

    # All other variables have the same dimensionality and chunk sizes.
    dims = [opts.dim_lon, opts.dim_lat, opts.dim_time]
    chunk_sizes = [try_get_chunk_size(d, nc.dimensions[d].size, opts.chunk_sizes) for d in dims]

    # Create all other variables.
    for col in data.columns:
        if col == opts.latitude_column or \
           col == opts.longitude_column or \
           col == opts.time_column:
            continue

        fmt = get_nc_datatype(str(data[col].dtype))
        create_var_if_not_exists(nc, col, fmt, dims, opts.compression_level
                                 , COMPRESSION_ZLIB, chunksizes = chunk_sizes)

    # TODO: Write metadata.

def is_coord_column(col: str, opts: Options):
    return col == opts.latitude_column or col == opts.longitude_column or \
           col == opts.time_column

def copy_data(opts: Options, data: pandas.DataFrame, nc: Dataset):
    """
    Write all data in the dataframe to the netcdf file.
    """
    # Get the dimension order/names in terms of column
    dims = [opts.dim_lon, opts.dim_lat, opts.dim_time]

    dim_sizes = [nc.dimensions[d].size for d in dims]
    chunk_sizes = [try_get_chunk_size(d, nc.dimensions[d].size, opts.chunk_sizes) for d in dims]

    niter = [size // chunk_size for (size, chunk_size) in zip(dim_sizes, chunk_sizes)]

    xds = xarray.Dataset.from_dataframe(data.set_index(dims))
    # xds.to_netcdf(path)
    for col in data.columns:
        if col in nc.dimensions:
            continue
        else:
            var = nc.variables[col]
            for i in range(niter[0]):
                ilow = i * chunk_sizes[0]
                ihigh = min(dim_sizes[0], ilow + chunk_sizes[0])
                ir = range(ilow, ihigh)
                for j in range(niter[1]):
                    jlow = j * chunk_sizes[1]
                    jhigh = min(dim_sizes[1], jlow + chunk_sizes[1])
                    jr = range(jlow, jhigh)
                    for k in range(niter[2]):
                        klow = k * chunk_sizes[2]
                        khigh = min(dim_sizes[2], klow + chunk_sizes[2])
                        kr = range(klow, khigh)
                        chunk = xds[col][ir, jr, kr]
                        var[ir, jr, kr] = chunk

def write_output_file(opts: Options, data: pandas.DataFrame):
    """
    Write the specified dataframe to the output file.

    @param opts: Output file options.
    @param data: Data frame to be written.
    """
    if os.path.exists(opts.out_file):
        log_warning(f"Clobbering existing output file: {opts.out_file}")
        os.remove(opts.out_file)

    with open_netcdf(opts.out_file, True) as nc:
        init_outfile(opts, data, nc)
        copy_data(opts, data, nc)

def main(opts: Options):
    """
    Main function.

    @param opts: Parsed CLI options provided by the user..
    """
    data = read_input_file(opts)
    write_output_file(opts, data)

if __name__ == "__main__":
    # Parse CLI args
    opts = parse_args(argv)

    set_log_level(opts.log_level)
    set_show_progress(opts.report_progress)

    try:
        # Actual logic is in main().
        main(opts)
        print("\nFile converted successfully!")
        print(f"Total duration: {get_walltime()}")
    except Exception as error:
        # Basic error handling.
        log_error(traceback.format_exc())
        exit(1)
