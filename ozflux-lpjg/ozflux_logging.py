# Logging utility functions.

import enum, sys
import datetime
from io import TextIOWrapper
import mpi4py

# Maximum length of a progress message. ie how many characters are used
# by printing the longest possible progress message?
MAX_PROGRESS_MSG_LEN = 17

class LogLevel(enum.IntEnum):
	NONE = 0,
	ERROR = 1,
	WARNING = 2,
	INFORMATION = 3,
	DIAGNOSTIC = 4,
	DEBUG = 5

class LpjVersion(enum.IntEnum):
	DAILY_GRASS = 0,
	LSM = 1

# Configuration options, which can be set via one of the below
# functions. Best not to set these directly from user code.
_log_level: LogLevel
_log_level = LogLevel.WARNING

_show_progress: bool
_show_progress = False

_warnings_as_errors: bool
_warnings_as_errors = False

# Time at which execution began.
_start_time: datetime.datetime
_start_time = datetime.datetime.now()

# Time of first progress report. Having this as a separate variable to
# _start_time allows the caller to perform some processing before progress
# reporting begins without influencing the ETA aspect of progress reports.
_progress_reporting_start: datetime.datetime
_progress_reporting_start = datetime.datetime.now()

_progress_end: str
_progress_end = "\r" if sys.stdout.isatty() else "\n"
if mpi4py.MPI.COMM_WORLD.size > 1:
	_progress_end = "\n"

_mpi_pfx: bool
_mpi_pfx = False

def set_use_mpi_pfx(mpi_pfx: bool):
	global _mpi_pfx
	_mpi_pfx = mpi_pfx

def set_warnings_as_errors(warnings_as_errors: bool):
	"""
	Treat all warnings as errors (true to enable, false to disable).
	"""
	global _warnings_as_errors
	_warnings_as_errors = warnings_as_errors

def set_log_level(log_level: LogLevel):
	"""
	Set the log level, which controls which messages are written to the
	log.
	"""
	global _log_level
	_log_level = log_level

def set_show_progress(show_progress: bool):
	"""
	Set whether progress messages will be displayed.
	"""
	global _show_progress
	_show_progress = show_progress

def _clear_line(file: TextIOWrapper):
	"""
	Clear a line by writing empty spaces followed by a carriage return,
	in order to remove any progress report written to this line.
	"""
	print(" " * MAX_PROGRESS_MSG_LEN, file = file, end = "\r")

def log(msg: str, log_level: LogLevel):
	"""
	Write a log message.
	"""
	# I'm putting this check here, rather than in log_warning(), in case
	# this function is called directly from user code.
	if log_level == LogLevel.WARNING:
		if _warnings_as_errors:
			raise ValueError(msg)
		else:
			msg = f"WARNING: {msg}"

	if _mpi_pfx:
		msg = f"[node {mpi4py.MPI.COMM_WORLD.rank}] {msg}"

	# todo: custom log file as CLI arg?
	if log_level <= _log_level:
		file = sys.stderr if log_level == LogLevel.ERROR else sys.stdout
		_clear_line(file = file)
		print(msg, file = file)

def log_error(msg: str):
	"""
	Write an error message.
	"""
	log(msg, LogLevel.ERROR)

def log_warning(msg: str):
	"""
	Write a warning message.
	"""
	log(msg, LogLevel.WARNING)

def log_information(msg: str):
	"""
	Write an information message.
	"""
	log(msg, LogLevel.INFORMATION)

def log_diagnostic(msg: str):
	"""
	Write a diagnostic message.
	"""
	log(msg, LogLevel.DIAGNOSTIC)

def log_debug(msg: str):
	"""
	Write a debug message.
	"""
	log(msg, LogLevel.DEBUG)

def log_progress(progress: float):
	"""
	Write a progress message.

	@param progress: Current progress in range [0, 1].
	"""
	global _show_progress
	global _progress_reporting_start
	global _progress_end
	if progress > 1:
		log_warning("Attempted to display progress > 1")

	current_time = datetime.datetime.now()
	elapsed = current_time - _progress_reporting_start
	elapsed = elapsed - datetime.timedelta(microseconds = elapsed.microseconds)
	total = elapsed / progress
	remaining = total - elapsed
	remaining = remaining - datetime.timedelta(microseconds = remaining.microseconds)

	if _show_progress:
		print("Working: %.2f%%; elapsed: %s; remaining: %s               " % (100 * progress, elapsed, remaining), end = _progress_end)

def get_walltime() -> datetime.timedelta:
	"""
	Get the total amount of walltime that has elapsed since program start.
	"""
	return datetime.datetime.now() - _start_time

def init_walltime():
	global _progress_reporting_start
	_progress_reporting_start = datetime.datetime.now()
