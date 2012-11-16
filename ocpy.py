#!/usr/bin/env python
#
#   Copyright (c) 2012 by Michael Goehler <somebody.here@gmx.de>
#
#   This file is part of ocpy.
#
#   ocpy is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   ownCloudTray is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with ocpy. If not, see <http://www.gnu.org/licenses/>.
#

import sys, os, time, atexit, pyinotify, subprocess, threading, ConfigParser
from signal import SIGTERM 

class Daemon:
	"""
	A generic daemon class.

	Many thanks to Sander Marechal
	http://www.jejik.com/articles/2007/02/a_simple_unix_linux_daemon_in_python/
	"""
	def __init__(self, pidfile, stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
		self.stdin = stdin
		self.stdout = stdout
		self.stderr = stderr
		self.pidfile = pidfile
	
	def daemonize(self):
		"""
		do the UNIX double-fork magic, see Stevens' "Advanced 
		Programming in the UNIX Environment" for details (ISBN 0201563177)
		http://www.erlenstar.demon.co.uk/unix/faq_2.html#SEC16
		"""
		try: 
			pid = os.fork() 
			if pid > 0:
				# exit first parent
				sys.exit(0) 
		except OSError, e: 
			sys.stderr.write("fork #1 failed: %d (%s)\n" % (e.errno, e.strerror))
			sys.exit(1)
	
		# decouple from parent environment
		os.chdir("/") 
		os.setsid() 
		os.umask(0) 
	
		# do second fork
		try: 
			pid = os.fork() 
			if pid > 0:
				# exit from second parent
				sys.exit(0) 
		except OSError, e: 
			sys.stderr.write("fork #2 failed: %d (%s)\n" % (e.errno, e.strerror))
			sys.exit(1) 
	
		# redirect standard file descriptors
		sys.stdout.flush()
		sys.stderr.flush()
		si = file(self.stdin, 'r')
		so = file(self.stdout, 'a+')
		se = file(self.stderr, 'a+', 0)
		os.dup2(si.fileno(), sys.stdin.fileno())
		os.dup2(so.fileno(), sys.stdout.fileno())
		os.dup2(se.fileno(), sys.stderr.fileno())
	
		# write pidfile
		atexit.register(self.delpid)
		pid = str(os.getpid())
		file(self.pidfile,'w+').write("%s\n" % pid)
	
	def delpid(self):
		os.remove(self.pidfile)

	def start(self):
		"""
		Start the daemon
		"""
		# Check for a pidfile to see if the daemon already runs
		try:
			pf = file(self.pidfile,'r')
			pid = int(pf.read().strip())
			pf.close()
		except IOError:
			pid = None
	
		if pid:
			message = "pidfile %s already exist. Daemon already running?\n"
			sys.stderr.write(message % self.pidfile)
			sys.exit(1)
		
		# Start the daemon
		self.daemonize()
		self.run()

	def stop(self):
		"""
		Stop the daemon
		"""
		# Get the pid from the pidfile
		try:
			pf = file(self.pidfile,'r')
			pid = int(pf.read().strip())
			pf.close()
		except IOError:
			pid = None
	
		if not pid:
			message = "pidfile %s does not exist. Daemon not running?\n"
			sys.stderr.write(message % self.pidfile)
			return # not an error in a restart

		# Try killing the daemon process	
		try:
			while 1:
				os.kill(pid, SIGTERM)
				time.sleep(0.1)
		except OSError, err:
			err = str(err)
			if err.find("No such process") > 0:
				if os.path.exists(self.pidfile):
					os.remove(self.pidfile)
			else:
				print str(err)
				sys.exit(1)

	def restart(self):
		"""
		Restart the daemon
		"""
		self.stop()
		self.start()

	def run(self):
		"""
		Our subclass will override this method. It will be called after the process has been
		daemonized by start() or restart().
		"""



class ocpy(Daemon, pyinotify.ProcessEvent):
	"""
	The ocpy daemon
	"""
	def watch(self, directory):
		"""
		add a directory to inotify
		"""
		self.watchdesc = self.watchman.add_watch(directory, self.mask, rec=True)


	def unwatch(self):
		"""
		remove all directories from inotify
		"""
		self.watchman.rm_watch(self.watchdesc.values(), rec=True)


	def newThread(self, callback, args):
		"""
		child process to spawn
		"""
		#self.csyncProc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		self.csyncProc = subprocess.Popen(args)
		self.csyncProc.wait()
		callback(self.csyncProc.returncode)


	def cbThread(self, returncode):
		"""
		callback of the child process
		"""
		self.csyncInProgress = False

		if self.csyncSubmitAgain == True:
			self.sync()
		else:
			self.csyncTimer = threading.Timer(self.csyncTimeout, self.sync)
			self.csyncTimer.start()


	def sync(self):
		"""
		main synchronization method
		"""
		if self.csyncInProgress == False:
			self.csyncSubmitAgain = False
			self.csyncInProgress = True

			# create the csync command
			csyncArgs = [self.csyncExe, self.csyncLocalPath, self.csyncProtocol + '://' + self.csyncUser + ':' + self.csyncPassword + '@' + self.csyncHost + ':' + str(self.csyncPort) + self.csyncRemotePath + '/' + self.csyncSubfolder]

			# start csync
			self.csyncThread = threading.Thread(target=self.newThread, args=(self.cbThread, csyncArgs))
			self.csyncThread.start()
		else:
			self.csyncSubmitAgain = True


	def process_IN_CREATE(self, event):
		"""
		inotify event callback
		"""
		if event.name != '.csync_timediff.ctmp':
			self.sync()


	def process_IN_DELETE(self, event):
		"""
		inotify event callback
		"""
		if event.name != '.csync_timediff.ctmp':
			self.sync()


	def process_IN_MODIFY(self, event):
		"""
		inotify event callback
		"""
		if event.name != '.csync_timediff.ctmp':
			self.sync()


	def process_IN_MOVED_FROM(self, event):
		"""
		inotify event callback
		"""
		if event.name != '.csync_timediff.ctmp':
			self.sync()


	def process_IN_MOVED_TO(self, event):
		"""
		inotify event callback
		"""
		if event.name != '.csync_timediff.ctmp':
			self.sync()


	def run(self):
		"""
		superclass start point
		"""
                self.name = 'ocpy'
                self.version = '0.1.0'

                # internal status flags
                self.csyncInProgress = False
                self.csyncSubmitAgain = False

		# create default configuration object
		self.configDefault = ConfigParser.ConfigParser()
		self.configDefault.add_section('csync')
		self.configDefault.set('csync', 'exe',         '/usr/bin/csync')
		self.configDefault.set('csync', 'local_path',  os.environ['HOME'] + '/ownCloud')
		self.configDefault.set('csync', 'protocol',    'owncloud')
		self.configDefault.set('csync', 'user',        '')
		self.configDefault.set('csync', 'password',    '')
		self.configDefault.set('csync', 'host',        'localhost')
		self.configDefault.set('csync', 'port',        '80')
		self.configDefault.set('csync', 'remote_path', '/files/webdav.php')
		self.configDefault.set('csync', 'subfolder',   '')
		self.configDefault.set('csync', 'timeout',     '60')

		# read configuration file if exists
		self.configFile = os.path.expanduser('~/.config/' + self.name + '/' + self.name + '.conf')
		self.configFileExample = os.path.expanduser('~/.config/' + self.name + '/' + self.name + '.conf.example')
		self.config = ConfigParser.ConfigParser()
		if self.config.read(self.configFile) == []:
			configDir = os.path.dirname(self.configFile)
			old_umask = os.umask(077)
			if not os.path.exists(configDir):
				os.makedirs(configDir)
			with open(self.configFileExample, 'wb') as configFileExample:
				self.configDefault.write(configFileExample)
			with open(self.configFile, 'wb') as configFile:
				self.configDefault.write(configFile)
			os.umask(old_umask)
			if self.config.read(self.configFile) == []:
				print "configuration file %s is not accessible" % self.configFile
				sys.exit(1)

		# persist configuration to parent object
		self.csyncExe        = self.config.get('csync', 'exe')
		self.csyncLocalPath  = self.config.get('csync', 'local_path')
		self.csyncProtocol   = self.config.get('csync', 'protocol')
		self.csyncUser       = self.config.get('csync', 'user')
		self.csyncPassword   = self.config.get('csync', 'password')
		self.csyncHost       = self.config.get('csync', 'host')
		self.csyncPort       = self.config.getint('csync', 'port')
		self.csyncRemotePath = self.config.get('csync', 'remote_path')
		self.csyncSubfolder  = self.config.get('csync', 'subfolder')
		self.csyncTimeout    = self.config.getint('csync', 'timeout')

		# initialize inotify
		self.watchman = pyinotify.WatchManager()
		self.watchdesc = None
		self.mask = pyinotify.IN_DELETE | pyinotify.IN_CREATE | pyinotify.IN_MODIFY | pyinotify.IN_MOVED_FROM | pyinotify.IN_MOVED_TO
		self.notifier = pyinotify.ThreadedNotifier(self.watchman, self)
		self.notifier.start()

		# watch directory
		self.watch(self.csyncLocalPath)

		# sync
		self.sync()



if __name__ == "__main__":
	daemon = ocpy('/tmp/ocpy.pid', '/dev/null', '/tmp/ocpy.log', '/tmp/ocpy.log')
	if len(sys.argv) == 2:
		if 'start' == sys.argv[1]:
			daemon.start()
		elif 'stop' == sys.argv[1]:
			daemon.stop()
		elif 'restart' == sys.argv[1]:
			daemon.restart()
		elif 'run' == sys.argv[1]:
			daemon.run()
		else:
			print "Unknown argument: %s" % sys.argv[1]
			sys.exit(2)
		sys.exit(0)
	else:
		print "usage: %s start|stop|restart|run" % sys.argv[0]
		sys.exit(2)

