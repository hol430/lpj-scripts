from typing import Callable
import multiprocessing
import ozflux_logging

class _Job(multiprocessing.Process):
	"""
	Represents a parallel job.
	"""
	def __init__(self, id: int, weight: int
	    	, func: Callable[[Callable[[float], None]], None]
	      	, progress_reader: multiprocessing.connection.Connection
	    	, progress_writer: multiprocessing.connection.Connection):
		"""
		Create a new _Job instance.

		@param id: Unique ID assigned to this job (used for progress reporting).
		@param weight: Weighting of this job's progress relative to other jobs'.
		@param func: The function to be called which performs work.
		@param progres_reader: Read connection to the subprocess' stdout pipe.
		@param progres_writer: Write connection to the subprocess' stdout pipe.
		"""
		multiprocessing.Process.__init__(self)
		self.id = id
		self.weight = weight
		self.func = func
		self.progress_reader = progress_reader
		self.progress_writer = progress_writer
		self.progress = 0.0

	def _progress_local(self, progress: float, start: float, total_weight:float):
		"""
		Progress reporting function used when the job is run locally.

		@param progress: The new progress.
		@param start: The weight of all jobs completed before this one.
		@param total_weight: The total weight of all jobs.
		"""
		self.progress = progress
		overall = (start + self.weight * progress) / total_weight
		ozflux_logging.log_progress(overall)

	def run(self):
		# Do main processing.
		self.func(lambda p: self.progress_writer.send( (p, self.id) ))

		# Close progress reporter pipe.
		self.progress_writer.close()

	def run_local(self, start: float, total_weight: float):
		"""
		Run this job on the current thread (ie not in a separate process).

		@param start: Total weight of all jobs already finished.
		@param total_weight: Total weight of all jobs.
		"""
		self.func(lambda p: self._progress_local(p, start, total_weight))

class JobManager:
	def __init__(self, allow_parallel: bool):
		"""
		Create a new JobManager.

		@param allow_parallel: True iff jobs are allowed to run in parallel.
		"""
		# True iff jobs are allowed to run in parallel. False otherwise.
		self.allow_parallel = allow_parallel

		# Total weight of all jobs. Access to this is controlled by _weights_lock.
		self._total_weight: int = 0

		# List of all submitted jobs (not running jobs!).
		self._jobs: list[_Job] = []

		self._lock = multiprocessing.BoundedSemaphore(1)

	def _progress_reporter(self, progress: float, id: int):
		"""
		This function is called by the wait() function when a progress report is
		received from one of the child processes.

		@param progress: Progress of this job in range [0, 1].
		@param id: ID of the job which has reported its progress.
		"""

		job = self._jobs[id]

		weight = job.weight / self._total_weight

		job.progress = weight * progress

		# No need to check if in parallel mode, as the mutex is easily
		# obtained when running in serial mode.
		aggregate_progress = sum([j.progress for j in self._jobs])
		ozflux_logging.log_progress(aggregate_progress)

	def add_job(self, func: Callable[[Callable[[float], None]], None]
		      , weight: int = 1):
		"""
		Register a job with the job manager. A job can be any function which
		reports its progress.

		No progress reporting will occur until wait() is called.

		@param func: The job's execution function. This is any function which
					 reports progress via a callable argument.
		@param weight: Absolute weight for this job. Higher value means progress
					in this job counts for proportionately more out of the
					aggregate progress of all jobs. The way that the weight is
					calculated should be consistent over all jobs, and it must
					be positive.
		"""
		with self._lock.acquire():
			# Get a job ID.
			job_id = len(self._jobs)

			# Update job weights. Note that the newly-added job weight should have
			# index job_id.
			self._job_weights.append(weight)
			self._total_weight += weight

			# Create a pipe for 1-way communication (progress reporting).
			reader, writer = multiprocessing.connection.Pipe(duplex = False)

			# Start the process.
			job = _Job(job_id, func, reader, writer)

			# Close the writable end of the pipe now, to be sure that p is the
			# only process which owns a handle for it. This ensures that when p
			# closes its handle for the writable end, wait() will promptly
			# report the readable end as being ready.
			writer.close()

			# Store the process handle for later use.
			self._jobs.append(job)

	def run_parallel(self):
		"""
		Run all jobs in parallel and wait for them to finish.
		"""
		with self._lock.acquire():
			for job in self._jobs:
				job.start()
			self._wait()

	def run_single_threaded(self):
		"""
		Run all jobs one at a time, in the current thread, and wait for them to
		finish.
		"""
		with self._lock.acquire():
			cum_weight = 0
			for job in self._jobs:
				job.run_local(cum_weight, self._total_weight)
				cum_weight += job.weight

	def _wait(self):
		"""
		Wait for all parallel jobs to finish running. Note that no progress
		messages will be written until this is called.
		"""
		while self._readers:
			for reader in self._readers:
				try:
					msg = None
					if reader.poll():
						msg = reader.recv()
						(progress, process_index) = msg
						self._progress_reporter(progress, process_index)
				except EOFError:
					self._readers.remove(reader)

		# Wait for processes to exit (actually, they should have all finished by
		# the time we get to here).
		for process in self._jobs:
			process.join()
