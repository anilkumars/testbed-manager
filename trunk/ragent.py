#!/usr/bin/python
#
# Copyright 2010 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Manage all test operations on remote host, the system under test.

Classes:
  RemoteAgent
  Runner
  Machine
  LogParser

RemoteAgent, part of the TestBed package, executes jobs on a remote system
under test, once the calling program has copied all required files to the
remote system. RemoteAgent is designed to have one calling method for each type
of test it runs.

TestBed Implementation:
  Within the TestBed package, RemoteAgent has the following dependencies:
    TestBed: the entry point. Copies required files to remote hosts.
    harness.sh: shared functions within TestBed.
    yaml file: provides a dictionary of constants.

External modules:
  PyreRing: runs acceptance tests.

Runner is a base class to implement a test runner. The test runner of your
choice should be called from a method of Runner, and this method should get
called from the Run method, based on the name of the runner.

Machine is a class to get a system inventory and send it to a MySQL datastore.

LogParser is the class that will parse the log files of each test type that it
understands. It will set the values for all of the various tests.
"""

__author__ = 'kdlucas@gmail.com (Kelly Lucas)'
__version__ = '1.2'

import datetime
import glob
import optparse
import os
import platform
import shutil
import sys
import tempfile
import time

import MySQLdb

import harness


class RemoteAgent(object):
  """Controls activities on a remote host for the TestBed package."""

  def __init__ (self):
    """Parse command line iptions and the yaml config file.

    Args:
      All of the following options arguments are supported.
    """

    parser = optparse.OptionParser()
    parser.add_option('-c', '--config',
                      dest='yaml',
                      default='testbed.yaml',
                      help='Specify configuration file (yaml format)')
    parser.add_option('-d', '--debug',
                      dest='debug',
                      default='info',
                      type='choice',
                      choices=['debug', 'info', 'warning', 'error', 'critical'],
                      help='Specify debug log level, default is info')
    parser.add_option('-j', '--job',
                      dest='job',
                      type='choice',
                      choices=['accept', 'all', 'bench', 'dbench', 'ltp',
                               'ltpstress', 'net_stress', 'system_stress'],
                      help='Specify job type')
    parser.add_option('-o', '--op',
                      dest='op',
                      type='choice',
                      choices=['auto', 'clean', 'config', 'get', 'halt',
                               'query', 'reboot', 'run', 'update', 'version'],
                      help='Type of operation')
    parser.add_option('--pubkey',
                      dest='publickey',
                      default=None,
                      help='Filename of public key of test account.')
    parser.add_option('-r', '--reports',
                      dest='reports',
                      default=os.path.join(sys.path[0], 'reports'),
                      help='Specify the report directory, default is ./reports')
    parser.add_option('-u', '--user',
                      dest='user',
                      help='Specify user to run job. Defaults current user.')

    self.options, self.args = parser.parse_args()

    # Root shouldn't write to the normal report directory.
    uid = os.getuid()
    if uid == 0:
      logfile = os.path.join(tempfile.gettempdir(), 'ragent.log')
    else:
      logfile = os.path.join(self.options.reports, 'ragent.log')
    if not harness.SetReports(self.options.reports, logfile):
      print 'Error with report directory!'
      print 'Check the %s directory for permissions' % self.options.reports
      raise 'Report directory error'
    self.logger = harness.SetLogger('RAgent', logfile, self.options.debug)

    # Ensure the options selected look sane.
    if not self.options.op:
      self.logger.warning('Usage error: op is required.')
      Usage()
    if self.options.op in ['auto', 'get', 'query', 'run']:
      if not self.options.job:
        self.logger.warning('Usage error: job name is required for this op.')
        Usage()

    self.constants = {}
    self.suitefile = None
    self.ltp_home = None
    self.project = None
    self.exec_path = os.path.dirname(os.path.abspath(sys.argv[0])) 
    self.hostname = platform.node().split('.')[0]

    self.ytree = harness.ReadYamlFile(self.options.yaml)
    self._MakeConstants()
    self._SetJobName(self.options.job)

  def RunJob(self):
    """Execute the job specified.

    Returns:
      boolean, True = no errors, False = errors.
    There will be excessive output from the LTP test, so don't capture it.
    """

    status = self._ExtractSuite()
    if status:
      self._RunInventory()
      if self.job == 'accept':
        status = self._RunAccept()
      elif self.job in self.joblist:
        status = self._RunSuite()
      else:
        self.logger.error('Run function for %s job not defined', self.job)
        status = False
    else:
      self.logger.error('Error extracting suite.')

    return status

  def _SetJobName(self, job_name):
    """Validate job_name is defined in config file, and then set it.

    Args:
      job_name: string, the name of the job.
    Once job_name is validated, it will set self.job. jobs is a list of jobs
    defined in yaml file. If the job name is found: self.job = job_name.
    joblist will be populated with all defined jobs.
    """

    self.joblist = sorted(harness.GetTypes(self.ytree, 'jobs'))
    all_job_names = set(['all', 'stress']) | set(self.joblist)
    if job_name in all_job_names:
      self.job = job_name
    else:
      self.job = None

  def _MakeConstants(self):
    """Add local host variable data to self.constants.

    This operation needs to be performed on the remote system under test, since
    local runtime values are required.
    """

    constdict = harness.MakeDict(self.ytree, 'constants')
    constdict['ROOT'] = os.path.dirname(os.path.abspath(sys.argv[0]))
    self.constants.update(harness.MakeConstants(constdict))

    logname = harness.GetTimeString() + self.hostname
    self.constants.update(harness.GetVersion())

    # Construct a dictionary with needed keys from self.constants.
    log_vals = {'ACCEPTLOG': '.log',
                'ACCEPTRPT': '.accept',
                'AIMRPT': '.aim',
                'BUILDRPT': '.build',
                'BENCHRPT': '.html',
                'DBENCH': '.dbench',
                'LTPHTML': '.html',
                'LTPOUT': '.out',
                'LTPRPT': '.ltp',
                'NETSTRESS': '.netperf',
                'STRESSLOG': '.slog',
                'STRESSRPT': '.stress',
                'SYSTEM': '.system',
               }
    for key in log_vals:
      self.constants[key] = logname + log_vals[key]

    self.constants['SLOG'] = os.path.join(self.constants['ROOT'],
                                          self.constants['STRESSLOG'])
    self.constants['RRDHOME'] = os.path.join(self.constants['ROOT'],
                                             logname + '.rrd')
    self.constants['INVENTORY'] = os.path.join(self.constants['ROOT'],
                                               self.constants['INVFILE'])

  def _RunInventory(self):
    """Run a small inventory of the hardware/software config."""

    sut = Machine()
    sut.ReadLSBRel()
    sut.RunInventory()
    sut.SaveInventory(self.constants['INVENTORY'])
    # sut.SendToMySQL(self.constants['REPORTHOST'])
    # harness.SendToMySQL(self.constants, self.constants['DBTMACH'],
    #                     sut.fieldlist, sut.valuelist)
    harness.InsertToMySQL(self.constants, self.constants['DBTMACH'],
                          sut.summary)

  def _RunAccept(self):
    """Execute the acceptance test suite."""

    status = True
    lines = harness.ReadFile(self.constants['LSBFILE'])
    self._GetSuite(lines)
    suitepath = os.path.join(self.constants['SRCDIR'], self.suitefile)
    if not os.path.isfile(suitepath):
      self.logger.error('Unable to access: %s', suitepath)
      status = False
    else:
      testrunner = Runner('PyreRing', self.exec_path, self.suitefile,
                          self.constants, self.project)
      testrunner.Run()
    return status

  def _RunSuite(self):
    """Execute the test suite identified from self.job."""

    runcmd = self._PrepareSuite()
    if runcmd:
      self.logger.info('Executing: %s', runcmd)
      status = harness.ExecGetOutput(runcmd)
    else:
      self.logger.error('No value for runcmd!!')
      status = False

    return status

  def _CombineLogs(self, invfile, report):
    """Append report to invfile.

    Args:
      invfile: string, the inventory file.
      report: string, the report file.
    """

    fout = open(report, 'a')

    test_names = {'accept': 'Acceptance Test\n',
                  'bench': 'UnixBench BenchMark Results\n',
                  'dbench': 'DBench Test Time: %s hour\n' %
                       self.constants['STRESSTIME'],
                  'ltp': 'Linux Test Project\n',
                  'ltpstress': 'LTP Stress Test: %s hour\n' %
                       self.constants['STRESSTIME'],
                  'net_stress': 'NetPerf Benchmark: %s hour\n' %
                       self.constants['STRESSTIME'],
                  'srcfs': 'SrcFS Test\n',
                  'system_stress': 'System Stress Duration: %s hour\n' %
                       self.constants['STRESSTIME'],
                 }

    fout.write(test_names.get(self.job, 'Unknown Test'))
    fin = open(invfile, 'r')
    try:
      for line in fin:
        try:
          fout.write(line)
        except IOError, e:
          self.logger.error('Error appending inventory to report.')
          self.logger.error(e)
    finally:
      fin.close()

    fout.close()

  def SendReport(self):
    """Send logs to target host and results to Database.

    Returns:
      Boolean: False indicates problems sending log files or reporting results.
    """

    logs = self._GetLogs()
    if not os.path.isfile(logs['rptsrc']):
      try:
        fout = open(logs['rptsrc'], 'w')
        try:
          fout.write('NO DATA LOGGED: %s test has no logs.\n' % self.job)
        except IOError, e:
          self.logger.error('Error writing to new log file %s', logs['rptsrc'])
          self.logger.error(e)
      finally:
        fout.close()
    cmd = 'sudo chmod 666 %s' % logs['rptsrc']
    harness.ExecGetOutput(cmd)
    self._CombineLogs(self.constants['INVENTORY'], logs['rptsrc'])
    # SendLogs() is no longer necessary since we will send the log to the 
    # MySQL database, as it's part of the schema.
    # self._SendLogs(logs)
    reportdir = os.join.path(self.constants['ROOT'], 'reports')
    parser = LogParser( reportdir, 'info')
    parser.ProcessLog(logs['rptsrc'])
    # Create method to format result into fieldlist and valuelist for the
    # SendToMySQL function. It will also need to include the log file for
    # the session.

    return sent

  def _GetLogs(self):
    """Find and return a dictionary of pathnames for each log file.

    Returns:
      dictionary, key = logtype, value = pathname.
    """

    logfiles = {
                'logsrc': None,
                'rptsrc': None,
               }

    if self.job in ['accept', 'srcfs']:
      # Get the filename of the report file. One .txt file is expected.
      reports = os.path.join(self.constants['ROOT'], 'reports', '*.txt')
      try:
        report_files = glob.glob(reports)
      except IOError, e:
        self.logger.error('Error accessing %s', reports)
        self.logger.error(e)
      if report_files:
        logfiles['rptsrc'] = report_files[0]
        logfiles['logsrc'] = os.path.join(self.constants['ROOT'], 'reports',
                                          'powerring.log')
    elif self.job == 'ltp':
      reports = os.path.join(self.constants['ROOT'], self.ltp_home, 'results',
                             '*.ltp')
      logs = os.path.join(self.constants['ROOT'], self.ltp_home, 'output',
                          '*.html')
      output = os.path.join(self.constants['ROOT'], self.ltp_home, 'output',
                            '*.out')
      try:
        report_files = glob.glob(reports)
      except IOError, e:
        self.logger.error('Error accessing %s', reports, e)
      try:
        log_files = glob.glob(logs)
        out_files = glob.glob(output)
      except IOError, e:
        self.logger.error('Error accessing %s\n%s', logs, e)
      if report_files:
        logfiles['rptsrc'] = report_files[0]
      if log_files:
        logfiles['logsrc'] = log_files[0]
      elif out_files:
        logfiles['logsrc'] = out_files[0]
    elif self.job == 'ltpstress':
      logs = os.path.join(self.constants['ROOT'], '*.slog')
      stress_log = glob.glob(logs)
      if stress_log:
        logfiles['logsrc'] = stress_log[0]
        logfiles['rptsrc'] = stress_log[0]
      else:
        logfiles['logsrc'] = self.constants['STRESSRPT']
        logfiles['rptsrc'] = self.constants['STRESSRPT']
    elif self.job == 'net_stress':
      logs = os.path.join(self.constants['ROOT'], '*.netperf')
      net_stress_log = glob.glob(logs)
      if net_stress_log:
        logfiles['logsrc'] = net_stress_log[0]
        logfiles['rptsrc'] = net_stress_log[0]
      else:
        logfiles['logsrc'] = self.constants['NETSTRESS']
        logfiles['rptsrc'] = self.constants['NETSTRESS']
    elif self.job == 'system_stress':
      logs = os.path.join(self.constants['ROOT'], '*.system')
      system_stress_log = glob.glob(logs)
      if system_stress_log:
        logfiles['logsrc'] = system_stress_log[0]
        logfiles['rptsrc'] = system_stress_log[0]
      else:
        logfiles['logsrc'] = self.constants['SYSTEM']
        logfiles['rptsrc'] = self.constants['SYSTEM']
    elif self.job == 'dbench':
      logs = os.path.join(self.constants['ROOT'], '*.dbench')
      dbench_log = glob.glob(logs)
      print 'dbench_log: %s' % dbench_log
      if dbench_log:
        logfiles['logsrc'] = dbench_log[0]
        logfiles['rptsrc'] = dbench_log[0]
      else:
        logfiles['logsrc'] = self.constants['DBENCH']
        logfiles['rptsrc'] = self.constants['DBENCH']
    elif self.job == 'bench':
      logfiles['logsrc'] = self.constants['BENCHLOG'] + '.html'
      logfiles['rptsrc'] = self.constants['BENCHLOG']
    else:
      self.logger.error('Unknown log type: %s', self.job)
      return None

    return logfiles

  def _SendLogs(self, logs):
    """Copy logs to a common repository.

    Args:
      logs: dictionary, key = identifier, value = filename.
    Returns:
      boolean: True = logs sent ok, False = errors.
    """

    sent = True
    pkgs = {
        logs['logsrc']: logs['logdest'],
        logs['rptsrc']: logs['rptdest']}
    for pkg in pkgs:
      try:
        os.chmod(pkg, 0644)
      except IOError, e:
        self.logger.error('Error changing mode on %s\n%s', pkg, e)
      except OSError, e:
        self.logger.error('No access permissions on %s\n%s', pkg, e)
      cmd = 'scp -p %s %s:%s' % (pkg, self.constants['REPORTHOST'], pkgs[pkg])
      if harness.ExecGetOutput(cmd):
        sent = False

    return sent


  def _ExtractSuite(self):
    """Extract test suites before executing the tests.

    Returns:
      boolean, success = True, errors = False.
    """

    status = None
    self.logger.info('Preparing for %s testing.', self.job)

    if self.job == 'accept':
      tests = os.path.basename(self.constants['TESTSRC'])
    elif self.job == 'bench':
      tests = self.constants['BENCH']
    elif self.job in ['ltp', 'ltpstress']:
      tests = self.constants['LTP']
    elif self.job in ['dbench', 'net_stress', 'system_stress']:
      tests = None
      status = True
    elif self.job == 'srcfs':
      tests = os.path.basename(self.constants['SRCFSSRC'])
    else:
      tests = None
      status = False

    if tests:
      status = harness.TarExtractTGZ(tests, self.constants['ROOT'])
      if not status:
        self.logger.error('Error extracting test cases.')

    return status

  def _PrepareSuite(self):
    """Make, install, and configure test suites that require it.

    Returns:
      string, the complete command to execute the job.
    """

    runcmd = None
    if self.job == 'ltp':
      self.ltp_home = harness.BuildLTP(self.constants)
      if self.ltp_home:
        runcmd = ('sudo %s/runltp -p -l %s -o %s -g %s' %
                  (self.ltp_home,
                   self.constants['LTPRPT'],
                   self.constants['LTPOUT'],
                   self.constants['LTPHTML']))
    elif self.job == 'ltpstress':
      self.ltp_home = harness.BuildLTP(self.constants)
      if self.ltp_home:
        runcmd = ('sudo testscripts/ltpstress.sh -l %s -n -t %s' %
                  (self.constants['SLOG'], self.constants['STRESSTIME']))
    elif self.job == 'net_stress':
      timeout = self.constants['STRESSTIME'] * 3600
      try:
        os.chdir(self.constants['ROOT'])
      except IOError, e:
        self.logger.error('Error with %s\n%s', self.constants['ROOT'], e)
      runcmd = ('./netperf -d -H ostest -l %s > %s' %
          (timeout, self.constants['NETSTRESS']))
    elif self.job == 'system_stress':
      status = harness.InstallPackage('stress')
      if status:
        timeout = str(self.constants['STRESSTIME']) + 'h'
        try:
          os.chdir(self.constants['ROOT'])
        except IOError, e:
          # Logging this error is sufficient. It won't run if this fails.
          self.logger.error('Error with %s\n%s', self.constants['ROOT'], e)
        runcmd = ('sudo stress -c 8 -i 8 -m 4 -d 4 -t %s > %s' %
            (timeout, self.constants['SYSTEM']))
    elif self.job == 'dbench':
      status = harness.InstallPackage('dbench')
      if status:
        timeout = self.constants['STRESSTIME'] * 3600
        try:
          os.chdir(self.constants['ROOT'])
        except IOError, e:
          self.logger.error('Error with %s\n%s', self.constants['ROOT'], e)
        runcmd = ('dbench -D /usr/local/google -t %s 64 > %s' %
            (timeout, self.constants['DBENCH']))
    elif self.job == 'bench':
      self.bench_home = harness.BuildBench(self.constants)
      if self.bench_home:
        runcmd = 'java runbench'

    return runcmd

  def _GetSuite(self, lines):
    """Determine the acceptance suite based on the operating system.

    Args:
      lines, list of lines from a file.
    """

    lsbdict = {}
    for line in lines:
      if '=' in line:
        s = line.strip().split('=')
        lsbdict[s[0]] = s[1]
    suitedict = harness.MakeDict(self.ytree, 'jobs', self.job)
    suite_key = lsbdict['DISTRIB_CODENAME']
    self.suitefile = suitedict[suite_key]
    # Set a project name based on the distribution code name.
    self.project = suite_key

  def Config(self, user=None, pubkey=None, sudofile='/etc/sudoers'):
    """Configure a system under test for automated testing. This will alter the
    sudoers file, and add the public key for the TestBed user to the
    authorized_user file of the root account.

    Args:
      user: string, the user to add to the sudoer file.
      sudofile: string, filename to edit.
    Returns:
      boolean: True = success, False = errors.
    Config() must be run as root, so call ragent with sudo to run Config().
    """

    add_users = [self.constants['ROLE']]
    if user:
      print 'Adding user: %s' % user
      add_users.append(user)

    for username in add_users:
      self.logger.info('Checking user: %s', username)
      status = self._SudoConf(username, sudofile)
      if not status:
        self.logger.error('Error: %s not added to sudoers file', username)
        return status
    if pubkey:
      status = self._AddPublicKey(pubkey)
      if not status:
        self.logger.error('Error adding TestBed user public key')
        return status

    pkglist = harness.MakeDict(self.ytree, 'packages', 'pyrering')
    self._InstallPkgs(pkglist)

    return status

  def Clean(self):
    """Remove all old files from ROOT on system under test.

    Returns:
      boolean: True = Success, False = errors.
    """

    pathname = os.path.join(self.constants[ROOT], '*')
    cmd = 'sudo rm -rf %s' % pathname
    status = harness.ExecGetOutput(cmd)
    if status:
      self.logger.error('Error from command: %s', cmd)

    return status

  def _InstallPkgs(self, pkglist):
    """Install a list of packages.

    Args:
      pkglist: list of package names.
    Returns:
      boolean: True = success, False = errors.
    """

    for pkg in pkglist:
      cmd = 'sudo apt-get -y --force-yes install %s' % pkg
      status = harness.ExecGetOutput(cmd)
      if status:
        self.logger.error('Error installing package: %s', pkg)
    return status

  def _SudoConf(self, username, sudofile):
    """Edit /etc/sudoers to allow sudo without a password.

    Args:
      username: string, username to check in /etc/sudoers.
      sudofile: string, file to edit.
    Returns:
      boolean, True = success, False = errors
    This method will require a password from a user who has authority to sudo
    on the system under test.
    """

    tmpsudo = '/tmp/sudoers'
    append_string = '%s ALL=(ALL) NOPASSWD: ALL\n' % username
    status = False
    user_exists = self._CheckFile(username, sudofile)
    print 'user_exists status: %s' % user_exists
    if not user_exists:
      try:
        shutil.copy(sudofile, tmpsudo)
      except IOError, e:
        self.logger.error('Error backing up %s\n%s', sudofile, e)
        return status
      try:
        f = open(sudofile, 'a')
        try:
          f.write(append_string)
          status = True
        except IOError, e:
          self.logger.error('Error writing to %s\n%s', sudofile, e)
      finally:
        f.close()
    else:
      status = True

    return status

  def _AddPublicKey(self, pubkey):
    """Add the test account's public key to allow ssh without a password.

    This function will copy the public key of the test account into the
    authorized_keys file of the same user account. So, this user must exist on
    on all the machines you plan on testing on.  In your configuration yaml
    file, add the user@machine where the public key was generated to the
    constants[strings[PKVAL]]. You will find this string at the end of your
    public key. If authorized_keys exists, it will make a backup of that file.
    It also checks to see if the public key exists in this file, as we don't
    want two identical keys in this file.

    Returns:
      boolean, True = success, False = errors
    """

    authfile = os.path.expanduser('~/.ssh/authorized_keys')
    tmpauthfile = '/tmp/authorized_keys'
    keystring = self.constants['PKVAL']
    status = False

    try:
      pkf = open(pubkey, 'r')
      try:
        public_key = pkf.read()
      finally:
        pkf.close()
    except IOError, e:
      self.logger.error('Error reading %s\n%s', pubkey, e)
      return status

    if os.path.isfile(authfile):
      key_exists = self._CheckFile(keystring, authfile)
      print 'key_exists status: %s' % key_exists
      if not key_exists:
        try:
          shutil.copy(authfile, tmpauthfile)
        except IOError, e:
          self.logger.error('Error backing up %s\n%s', authfile, e)
          return status
        try:
          f = open(authfile, 'a')
          try:
            f.write(public_key)
            status = True
            # If we make it to this point it's ok to remove the backup copy.
            os.remove(tmpauthfile)
          finally:
            f.close()
        except IOError, e:
          self.logger.error('Error writing to %s\n%s', authfile, e)
          shutil.copy(tmpauthfile, authfile)
          status = False
      else:
        status = True
    else:
      try:
        f = open(authfile, 'w')
        try:
          f.write(public_key)
          status = True
        finally:
          f.close()
      except IOError, e:
        self.logger.error('Error writing to %s\n%s', authfile, e)
        status = False

    return status

  def _CheckFile(self, username, filename):
    """Search for a string in a file.

    Args:
      username: string, username to check.
      filename: string, filename to check for string username.
    Returns:
      Boolean: True if username is present, False if not found.
    """

    found = False
    f = open(filename, 'r')
    for line in f:
      rc = line.find(username)
      if rc != -1:
        found = True
    f.close()
    return found


class Runner(object):
  """Execute testcases by the specified test runner.

  There should be one method to setup and call the test runner of choice. Call
  that method from this class, and add a check in the Run method for the name of
  your runner.
  """

  def __init__(self, runner_name, exec_path, suitefile, constants, project):
    self.name = runner_name
    self.exec_path = exec_path
    self.suitefile = suitefile
    self.constants = constants
    self.project = project

  def Run(self):
    if self.name == 'PyreRing':
      return self._RunPyreRing()
    else:
      print 'Usage error: %s runner unknown' % self.name
      return -1

  def _RunPyreRing(self):
    """Configure and run the PyreRing test runner."""

    prcmd = 'python pyrering/pyrering.py --project %s --source_dir %s %s' % (
             self.project, self.constants['SRCDIR'], self.suitefile)
    status = os.system(prcmd)
    print status


class Machine(object):
  """A class to represent a machine we want to inventory.

  Machine class will rely upon lshw, a program that should be installed before
  running. lshw compiles a list of details about a machine, by in turn calling a
  number of programs to extract info, including information in the bios.
  Therefore, if the bios is incorrect, lshw will also be incorrect in what it
  reports. I made an conscious effort to not rely on what the OS detects, in
  order to give us some info on what the bios says we have compared to what the
  OS may report.

  Machine class will make heavy use of dictionaries, as I thought this was an
  easy way to store and retrieve details, as we could readily locate them based
  on a key.
  """

  def __init__(self):
    """Initialize a few variables and dictionaries we will use.

    Attributes:
      system, processor, bios, memory, video, nic, storage:
        dicts of string identifiers used with commands stored in the 'command'
        key of that dictionary.
        The 'command' key identifies the shell command to extract data.
      components: a list that holds the dictionary name of each subsystem we
        want to inventory.
      summary: dictionary to hold the values we want to track. The keys of
        this dictionary match the keys of all of the component dicts.
      desc: dictionary to describe each inventory component. The keys should
        match each key of the summary dictionary.
      basic_list: a list that contains summary/desc keys to print basic
        components.
    """

    self.system = {'command': 'sudo lshw -C system',
                   'form': 'description:',
                   'model': 'product:',
                   'serial': 'serial:',
                   'sysconfig': 'capabilities:',
                   'vendor': 'vendor:',
                  }

    self.processor = {'command': 'sudo lshw -C cpu',
                      'cpu_bits': 'width:',
                      'cpu_capability': 'capabilities:',
                      'cpu_capacity': 'capacity:',
                      'cpu_model': 'product:',
                      'cpu_speed': 'size:',
                      'cpu_vendor': 'vendor:',
                     }

    self.bios = {'command': 'sudo dmidecode -t bios',
                 'bios_date': 'Release Date:',
                 'bios_vendor': 'Vendor:',
                 'bios_version': 'Version',
                }

    self.memory = {'command': 'lshw -C memory',
                   'mem_size': 'size:',
                  }

    self.video = {'command': 'lshw -C video',
                  'video_memory': 'size:',
                  'video_model': 'product:',
                  'video_vendor': 'vendor:',
                 }

    self.nic = {'command': 'sudo lshw -C network',
                'nic_config': 'configuration:',
                'nic_mac': 'serial:',
                'nic_model': 'product:',
                'nic_speed': 'capacity:',
                'nic_vendor': 'vendor:',
                'nic_width': 'width:',
               }

    self.storage = {'command': 'lshw -C storage',
                    'dsk_config': 'configuration:',
                    'dsk_model': 'product:',
                    'dsk_speed': 'clock:',
                    'dsk_type': 'description:',
                    'dsk_vendor': 'vendor:',
                    'dsk_width': 'width:',
                   }

    # The list items should correspond to the name of each dictionary
    # that contains the elements we want to inventory. List items must be
    # already defined in this class.
    # TODO(kdlucas): populate list from an optional config file.
    self.components = [self.bios,
                       self.memory,
                       self.processor,
                       self.nic,
                       self.storage,
                       self.system,
                       self.video,
                      ]
    self.summary = {'arch': None,
                    'bios_date': None,
                    'bios_vendor': None,
                    'bios_version': None,
                    'cpu_bits': None,
                    'cpu_capability': None,
                    'cpu_capacity': None,
                    'cpu_model': None,
                    'cpu_qty': 0,
                    'cpu_speed': None,
                    'cpu_vendor': None,
                    'dsk_config': None,
                    'dsk_model': None,
                    'dsk_speed': None,
                    'dsk_type': None,
                    'dsk_vendor': None,
                    'dsk_width': None,
                    'form': None,
                    'kernel': None,
                    'mem_size': None,
                    'model': None,
                    'nic_config': None,
                    'nic_mac': None,
                    'nic_model': None,
                    'nic_speed': None,
                    'nic_vendor': None,
                    'nic_width': None,
                    'node': None,
                    'os_desc': None,
                    'os_distrib': None,
                    'os_rel': None,
                    'os_rev': None,
                    'serial': None,
                    'sysconfig': None,
                    'vendor': None,
                    'video_memory': None,
                    'video_model': None,
                    'video_vendor': None,
                   }

    self.desc = {'arch': 'Architecture:',
                 'bios_date': 'Bios Date:',
                 'bios_vendor': 'Bios Vendor:',
                 'bios_version': 'Bios Version:',
                 'cpu_bits': 'Processor Data Width:',
                 'cpu_capability': 'Processor Capabilities:',
                 'cpu_capacity': 'Processor Maximum Speed:',
                 'cpu_model': 'Processor Model:',
                 'cpu_qty': 'Number of Processors:',
                 'cpu_speed': 'Processor Speed:',
                 'cpu_vendor': 'Processor Vendor:',
                 'dsk_config': 'Disk Controller Options:',
                 'dsk_model': 'Disk Controller Model:',
                 'dsk_speed': 'Disk Controller clock rate:',
                 'dsk_type': 'Disk Interface:',
                 'dsk_vendor': 'Disk Controller Vendor:',
                 'dsk_width': 'Disk Controller width:',
                 'form': 'Form Factor:',
                 'os_rel': 'Distribution Release:',
                 'os_desc': 'OS Description',
                 'kernel': 'Kernel Version:',
                 'mem_size': 'System Memory:',
                 'model': 'System Model:',
                 'nic_config': 'Network Card Configuration:',
                 'nic_mac': 'Network Card MAC Address:',
                 'nic_model': 'Network Card Model:',
                 'nic_speed': 'Network Card Speed:',
                 'nic_vendor': 'Network Card Vendor:',
                 'nic_width': 'Network Card Data Width:',
                 'node': 'Host Name:',
                 'os_distrib': 'Distribution:',
                 'os_rev': 'Codename:',
                 'serial': 'System Serial:',
                 'sysconfig': 'System Configuration:',
                 'vendor': 'System Vendor:',
                 'video_model': 'Graphics Adapter Model:',
                 'video_vendor': 'Graphics Adapter Vendor:',
                 'video_memory': 'Graphics Adapter Memory:',
                }

    # Maintain the order of this list for reporting purposes.
    # The most important information should go first, and PowerRing uses 15
    # items to place at the top of a report.
    self.basic_list = ['os_distrib',
                       'os_rel',
                       'os_rev',
                       'os_desc',
                       'model',
                       'kernel',
                       'arch',
                       'cpu_model',
                       'cpu_qty',
                       'mem_size',
                       'bios_date',
                       'bios_vendor',
                       'video_model',
                       'nic_model',
                       'dsk_model',
                      ]

    # fieldlist = database fieldnames, and valuelist = their corresponding
    # values. TODO: Just submit summary dictionary..
    self.fieldlist = []
    self.valuelist = []

    # This self test will report errors with return codes. We don't need to
    # catch these return codes unless your tests have a dependency on this
    # module or dictionary keys. If there is an error we can still get useful
    # information from the inventory, and allow the test cases to run.
    self._TestDictKeys()

  def _TestDictKeys(self):
    """A simple test to check that dictionary keys match.

    Args:
      None.

    Returns:
      retval: an integer that could be used if that's more convenient than
      using output from the error messages.

    This will gather all the dictionary keys of the pertinent dictionaries, and
    ensure the keys are identical. Component identification, descriptions, and
    the search strings rely on matching keys to track the data.

    By definition, the components list contains all of our component dicts.
    The set of all keys in the component dicts should be a subset of the
    summary dictionary keys. The summary and desc keys should be identical.
    I'm using sets because sets has some nice features that identify subsets
    and the differences in 2 sets.

    retval can be caught if necessary. retval will equal the total number of
    dict key errors.
    """

    retval = 0
    kcomp = set()
    for item in self.components:
      k = set(item.keys())
      k.remove('command')  # This is a special key that we know needs removed.
      # Ensure there are no duplicates within the component dictionaries. If we
      # don't do this check, duplicates will be silently ignored.
      dups = kcomp.intersection(k)
      if dups:
        print 'Error: key duplicates found in component dictionaries!'
        print 'Check %s for duplicates.' % k
        print 'Duplicate keys: %s' % dups
        retval += 1
      kcomp.update(k)
    ksummary = set(self.summary.keys())
    kdesc = set(self.desc.keys())
    kbasic = set(self.basic_list)

    diff = ksummary.difference(kdesc)
    if diff:
      print 'Error: dictionary keys do not match.'
      print 'Check keys: %s' % diff
      retval += 1
    for k in [kcomp, kbasic]:
      subset = k.issubset(ksummary)
      if not subset:
        print 'Error: dictionary key error in the basic list.'
        print 'Keys in %s not in summary dictionary.' % k
        retval += 1

    return retval

  def ReadLSBRel(self):
    """Read /etc/lsb-release, and parse contents into dictionary.

    This will parse all the key/value pairs in lsb-release and use the
    left-hand column as a key to values in the right hand column.

    Args:
      None.

    Returns:
      None.
    """

    lsbdict = {}  # to hold our key value pairs
    lsbfname = '/etc/lsb-release'

    try:
      lsbfh = open(lsbfname)
    except IOError, err:
      print 'Error opening %s\n%s' % (lsbfname, err)
      raise

    lsblist = lsbfh.readlines()
    lsbfh.close()

    for line in lsblist:
      if line:
        line = line.strip()
        key, value = line.split('=')
        value = value.strip('"')
        lsbdict[key] = value
    self.summary['os_rel'] = lsbdict['DISTRIB_RELEASE']
    self.summary['os_desc'] = lsbdict['DISTRIB_DESCRIPTION']
    self.summary['os_distrib'] = lsbdict['DISTRIB_ID']
    self.summary['os_rev'] = lsbdict['DISTRIB_CODENAME']

  def RunInventory(self):
    """Run through all the dictionaries to get an inventory.

    This will call GetInventory() which will process the actual command and
    parse the output. RunInventory() is a simple way to cycle through a list of
    components. Each component is a dictionary, and the 'command' key maps to
    the actual os level command that provides the inventory data. The other
    key's provide strings that we use to match the relevant data we care about.
    All of these keys are identical to keys in the desc and summary
    dictionaries, which hold the descriptions and data respectively.

    Args:
      None.

    Returns:
      None.
    """

    for item in self.components:
      self.GetInventory(item)

    system_os = platform.uname()
    self.summary['node'] = system_os[1]
    self.summary['kernel'] = system_os[2]
    self.summary['arch'] = system_os[4]

    if not self.summary['video_memory']:
      # Often video memory is not specified in lshw or dmidecode.
      cmd = 'lspci | grep VGA | cut -d" " -f1 | xargs lspci -v -s'
      cmdoutput = harness.ExecGetOutput(cmd, output=True)

      for line in cmdoutput.splitlines():
        if ' prefetchable' in line:
          memsize = line.split('=')
          self.summary['video_memory'] = memsize[1][:-1]

    for key in self.summary:
      if not self.summary[key]:
        self.summary[key] = 'unknown'

    # Format the date for our database.
    newdate = datetime.datetime(*time.strptime(self.summary['bios_date'],
                                               "%m/%d/%Y")[0:5])
    self.summary['bios_date'] = datetime.datetime.strftime(newdate, "%Y/%m/%d")

    # Put the keys and values in lists for database insertion.
    for k in self.summary:
      self.fieldlist.append(k)
      self.valuelist.append(self.summary[k])

  def GetInventory(self, component):
    """Collect machine data in place in summary dictionary.

    This function will attempt to execute the values from the commands
    dictionary. Using text markers from component dicts, it will place the
    resulting text in the summary dictionary. This function manipulates the
    output to eliminate output we don't care about.

    Args:
      component: the name of the dictionary we're passing in.

    Returns:
      None.
    """

    # A general marker for a cpu flag.
    cpu_marker = '*-cpu'
    cpu_count = 0

    cmd = component['command']
    cmdoutput = harness.ExecGetOutput(cmd, output=True)

    # The following for loop takes all of the output from the command, and
    # breaks it into one line. There is specific logic for the cpu_marker to
    # keep track of the qty of cpus. The delimiter character is used because
    # there are various sections of output that have identical keys. This code
    # depends on using the first instance of these keys to get the correct
    # values. To do this, I've used a counter to count the number of times we
    # see a delimiter character sequence. As long as that counter doesn't
    # exceed 1, we'll add the value to the summary dictionary. There are
    # identical key fields in the output, like 'size', 'vendor', 'capacity',
    # etc. In all cases we only care about the 1st occurrence of these strings.
    # Therefore, to prevent getting invalid data a counter ensures only data
    # from the first occurrence of matching string is stored.
    for line in cmdoutput.splitlines():
      if cpu_marker in line:
        cpu_count += 1
      for item, key in component.iteritems():
        if item != 'command' and key in line:
          if not self.summary[item]:
            fields = line.split(component[item])
            self.summary[item] = fields[1].lstrip()
    if cpu_count > 0:                      # Prevents qty from getting reset.
      self.summary['cpu_qty'] = cpu_count  # If component is not processor.


  def PrintInventory(self, detail):
    """Print out inventory results.

    This method prints the contents of the summary dictionary.
    The amount of data depends on the value passed from detail.

    Args:
      detail: a string to determine the level of detail to output, and
      possibly a future determination of format.

    Returns:
      None.
    """

    if detail == 'basic':
      for item in self.basic_list:
        print "%-25s  %-20s" % (self.desc[item], self.summary[item])
    elif detail == "detailed":
      for key in self.desc:
        print "%-27s  %-20s" % (self.desc[key], self.summary[key])

  def SaveInventory(self, filename):
    """Save the inventory results to a file.

    This method will save all of the key value pairs to a file. This can be
    used for future reads to prevent another inventory of a system.

    Args:
      filename: the name of a file to save the inventory to.

    Returns:
      None.
    """

    fout = open(filename, 'w')

    try:
      for item in self.basic_list:
        try:
          fout.write("%-25s  %-20s\n" % (self.desc[item], self.summary[item]))
        except IOError, e:
          print e
          raise
      try:
        fout.write("\n**********DETAILED PLATFORM INFORMATION************\n")
      except IOError, e:
        print e
        raise
      for key in self.desc:
        try:
          fout.write("%-27s  %-20s\n" % (self.desc[key], self.summary[key]))
        except IOError, e:
          print e
          raise
    finally:
      fout.close()


class LogParser(object):
  """Parse log files and report the results.

  This class requires a method for each type of log file you will be parsing. It
  will also require a method for each data base schema, since this will send
  results directly to the database.
  """

  # The values of SUITE_CATEGORY are used to identify the log type.
  SUITE_CATEGORY = {'Accept': 'PyreRing Test Report',
                    'DBench': 'dbench',
                    'LTP': 'Linux Test Project',
                    'Net_Stress': 'NetPerf Benchmark',
                    'Stress': 'Stress Test',
                    'System_Stress': 'System Stress Duration',
                    'UnixBench': 'BYTE UNIX Benchmarks',
                   }
  LOG_KEYS = {'Accept': ['SETUP', 'TEARDOWN'],
              'DBench': ['Throughput', 'Failed'],
              'LTP': ['PASS', 'FAIL'],
              'Net_Stress': ['remote results obtained', 'could not'],
              'Stress': ['PASS', 'FAIL'],
              'System_Stress': ['successful run completed',
                                'failed run completed'],
             }

  def __init__(self, reportdir, debug_level):
    """Initialize the LogParser class.

    Initialize a logger and set attributes to None or empty sets.

    Args:
      reportdir: string, pathname of report directory.
      debug_level: string, debug level.
    """

    runlog = os.path.join(reportdir, 'reporter.log')
    self.logger = harness.SetLogger('LogParser', runlog, debug_level)

    self.arch = None
    self.biosdate = None
    self.build = None
    self.cpu = None
    self.cpu_quantity = None
    self.description = None
    self.id = None
    self.kernel = None
    self.logname = None
    self.logtype = None
    self.memory = None
    self.model = None
    self.name = None
    self.release = None
    self.serial = None
    self.start = None
    self.version = None
    
    self.results = {}
    self.output = {}
    self.suites = []
    self.tests = []

  def ProcessLog(self, filename):
    """Read log file, parse it, and assign values to variables.

    Args:
      filename: string, pathname of log file with test results.
    """

    tokens = {'arch': 'Architecture:',
              'biosdate': 'Bios Date:',
              'code': 'Codename:',
              'cpu': 'Processor Model:',
              'cpu_quantity': 'Number of Processors:',
              'dist': 'Distribution:',
              'kernel': 'Kernel Version:',
              'memory': 'System Memory:',
              'model': 'System Model:',
              'node': 'Host Name:',
              'release': 'OS Release:',
              'score': 'System Benchmarks Index Score',
              'serial': 'System Serial:',
              'start': 'Start Time:',
              'version': 'LTP_Release:',
             }
    output_ext = '.out'

    # Construct a dict with the keys of the tokens{}, and value of None.
    mach = dict([(key, None) for key in tokens.iterkeys()])

    logfile = open(filename, 'r')
    try:
      log = logfile.readlines()
    finally:
      logfile.close()
    # Get any output files and put in output dictionary.
    # Output file have an extension marked by output_ext.
    reportdir = os.path.dirname(filename)
    for f in os.listdir(reportdir):
      if f.endswith(output_ext):
        fpath = os.path.join(reportdir, f)
        fkey = f.rstrip(output_ext)
        try:
          fout = open(fpath, 'r')
        except IOError, e:
          self.output[fkey] = e
        else:
          try:
            try:
              tempout = fout.readlines()
              self.output[fkey] = ''.join(tempout)
            except IOError:
              self.output[fkey] = None
          finally:
            fout.close()

    self._ParseLog = self._GetFunction(log, filename)
    status = self._ParseLog(log, mach, tokens)
    self._AssignValues(mach)

  def _GetFunction(self, log, filename):
    """Determine the method to return based on the log type.

    Args:
      log: a list of all lines of result log.
      filename: string, pathname of results log.
    Returns:
      pointer of proper method to parse logs of that type.
    Raises:
      LogError: handles unknown log formats
    """

    log_methods = {'Accept': self._ParsePRLog,
                   'DBench': self._ParseDBenchLog,
                   'LTP': self._ParseLTPLog,
                   'Net_Stress': self._ParseNetStressLog,
                   'Stress': self._ParseStressLog,
                   'System_Stress': self._ParseSystemStressLog,
                   'UnixBench': self._ParseUnixBenchLog,
                  }

    for line in log:
      for key in self.SUITE_CATEGORY:
        if self.SUITE_CATEGORY[key] in line:
          self.logtype = key
          return log_methods[key]
    # If we get this far it's an error. Create an error message and raise it.
    error_msg = 'Unable to identify %s.' % filename
    self.logger.error(error_msg)

  def _ParsePRLog(self, log, mach, tokens):
    """Parse the PyreRing Log file format.

    Args:
      log: all lines of log file.
      mach: dict of machine values for this session
      tokens: dict of strings to identify value markers.
    The following variables will be set:
      self.test list
      self.results dictionry
      self.suites
      mach dictionary
    """

    delim = '/'  # Used to separate path from testcase name.
    suitemark = 'Suites:'  # Used to find the suite name.
    testcase_mark = 'TESTCASE:'
    tokens['version'] = 'Kernel Version'

    for line in log:
      if testcase_mark in line:
        if not self._IsTestResult(line, self.logtype):
          sections = line.split()
          if len(sections) > 1:
            testcase_info = sections[1].split(delim)
            if testcase_info:
              testcase_name = testcase_info[-1]
          self.tests.append(testcase_name)
          self.results[testcase_name] = sections[2]
      elif suitemark in line:
        if not self._IsTestResult(line, self.logtype):
          self.suites = eval(self._GetSubString(line))
      else:
        for key, value in tokens.iteritems():
          if value in line:
            if key == 'node':
              mach[key] = self._GetShortHostName(line)
            else:
              mach[key] = self._GetSubString(line)


  def _ParseLTPLog(self, log, mach, tokens):
    """Parse the Linux Test Project log file.

    This method will create objects to hold data it parses. There is currently
    only one component and suite, so hard code them until that changes.
    Args:
      log: a list of all lines from the log file.
      mach: dict of machine values for this session.
      tokens: dict of strings to identify value markers.
    The following variables will be set:
      self.comp_set dictionary
      self.tests list
      self.results dictionary
      mach dictionary
    """

    comp = 'kernel'
    suite = 'LTP'

    self.comp_names.append(comp)
    self.suites.append(suite)
    for line in log:
      if self._IsTestResult(line, self.logtype):
        sections = line.split()
        testcase_name = sections[0]
        self.tests.append(testcase_name)
        self.results[testcase_name] = sections[1]
        if comp in self.comp_set:
          self.comp_set[comp].add(testcase_name)
        else:
          self.comp_set[comp] = set([testcase_name])
      else:
        tempdict = self._SetMachineName(tokens, line)
        for key in tempdict:
          mach[key] = tempdict[key]

  def _ParseStressLog(self, log, mach, tokens):
    """Parse the Linux Test Project Stress log file.

    This method will create objects to hold data it parses. Hard code the
    component and suite until there is more than one type of each.
    Args:
      log: a list of all lines from the log file.
      mach: dict of machine values for this session.
      tokens: dict of strings to identify value markers.
    The following variables will be set:
      self.com_names list
      self.suites list
      self.tests list
      self.results dictionary
      self.comp_set dictionary
      self.description string
      mach dictionary
    """

    comp = 'stress'
    suite = 'stress'
    duration = 'Stress Test:'

    self.comp_names.append(comp)
    self.suites.append(suite)
    for line in log:
      if self._IsTestResult(line, self.logtype):
        sections = line.split()
        if len(sections) > 1:
          testcase_name = sections[0]
          if testcase_name not in self.tests:
            self.tests.append(testcase_name)
          self.results[testcase_name] = sections[1]
          if comp in self.comp_set:
            self.comp_set[comp].add(testcase_name)
          else:
            self.comp_set[comp] = set([testcase_name])
      elif duration in line:
        self.description = self._GetSubString(line)
      else:
        tempdict = self._SetMachineName(tokens, line)
        for key in tempdict:
          mach[key] = tempdict[key]

  def _ParseSystemStressLog(self, log, mach, tokens):
    """Parse the output from System Stress.

    Args:
      log: a list of all lines from the log file.
      mach: dict of machine values for this session.
      tokens: dict of strings to identify value markers.
    """

    comp = 'system_stress'
    suite = 'system_stress'
    testcase_name = 'system_stress_test'
    duration = 'System Stress Duration'

    self._ParseTxtLog(log, mach, tokens, comp, suite, testcase_name, duration)

  def _ParseNetStressLog(self, log, mach, tokens):
    """Parse the output from NetPerf.

    Args:
      log: a list of all lines from the log file.
      mach: dict of machine values for this session.
      tokens: dict of strings to identify value markers.
    """

    comp = 'net_stress'
    suite = 'net_stress'
    testcase_name = 'netperf_stress_test'
    duration = 'NetPerf Run Time'

    self._ParseTxtLog(log, mach, tokens, comp, suite, testcase_name, duration)

  def _ParseDBenchLog(self, log, mach, tokens):
    """Parse the output from DBench.

    Args:
      log: a list of all lines from the log file.
      mach: dict of machine values for this session.
      tokens: dict of strings to identify value markers.
    """

    comp = 'dbench'
    suite = 'dbench'
    testcase_name = 'dbench_stress_test'
    duration = 'Dbench Run Time'

    self._ParseTxtLog(log, mach, tokens, comp, suite, testcase_name, duration)

  def _ParseTxtLog(self, log, mach, tokens, comp, suite, name, duration):
    """Run through the log and parse output.

    This routine can be used for any generic log which doesn't have the actual
    testcase names included in the log. The following structures get updated:
      self.comp_names
      self.suites
      self.comp_set
      self.tests
      self.results
      self.description

    Args:
      log: a list of lines from a test log
      mach: dict of machine values for this session
      tokens: dict of strings to identify value markers
      comp: string, name of the component
      suite: string, name of the suite
      name: string, name of the test case
      duration: integer, number of hours testcase runs.
    """

    self.comp_names.append(comp)
    self.suites.append(suite)
    if comp in self.comp_set:
      self.comp_set[comp].add(name)
    else:
      self.comp_set[comp] = set([name])
    if name not in self.tests:
      self.tests.append(name)
    for line in log:
      if self._IsTestResult(line, self.logtype):
        if self.LOG_KEYS[self.logtype][0] in line:
          self.results[name] = 'PASS'
        else:
          self.results[name] = 'FAIL'
      if duration in line:
        self.description = self._GetSubString(line)
      else:
        tempdict =self._SetMachineName(tokens, line)
        for key in tempdict:
          mach[key] = tempdict[key]

  def _ParseUnixBenchLog(self, logs, mach, tokens):
    """Parse the UnixBench log and send the final score to a database.

    Args:
      log: log of UnixBench performance test.
      mach: dict of machine values for this session.
      tokens: dict of strings to identify value markers.
    Returns:
      boolean: True = report was parsed ok, False = problem.
    """

    name = 'UnixBench'
    if name not in self.tests:
      self.tests.append(name)

    values = {'arch': None,
              'kern': None,
              'model': None,
              'rel': None,
              'score': None,
              'url': report_name,
             }

    logfile = open(logs['rptsrc'], 'r')
    try:
      try:
        log = logfile.readlines()
      except IOError, e:
        self.logger.error('Error reading log: %s\n%s', logs['rptsrc'], e)
    finally:
      logfile.close()

    for line in log:
      for key in tokens:
        if tokens[key] in line:
          sections = line.split(token[key])
          if len(sections) > 1:
            values[key] = sections[1].strip()

    self.results[name] = values['score']

  def SendSummary(self, build, address):
    """Calculate and email summary of test results.

    Args:
      build: build object
      address: string, email address.
    """

    tests_passed = 0
    tests_failed = 0
    tests_error = 0
    tests_timeout = 0

    message = emailmessage.EmailMessage()

    ts_url = 'http://ts/run?projectId=%s&buildId=%s' % (self.projid, build.id)
    for result in self.results:
      if self.results[result] == 'PASS':
        tests_passed += 1
      elif self.results[result] == 'FAIL':
        tests_failed += 1
      elif self.results[result] == 'ERROR':
        tests_error += 1
      elif self.results[result] == 'TIMEOUT':
        tests_timeout += 1

    sessioninfo = ('Test Session: %s\nURL: %s\n\n' % (self.name, ts_url))
    testinfo = ('Passed: %d\nFailed: %d\nErrors: %d\nTimed Out: %d' %
                (tests_passed, tests_failed, tests_error, tests_timeout))
    body = sessioninfo + testinfo
    from_address = 'opsqa-testbed'
    message.SetMessage('opsqa-testbed',
                        address,
                        self.name,
                        body,
                        None)
    log_message = message.Send()
    if log_message:
      logging.info(log_message)
    else:
      logging.info('email sent to %s', address)

  def _AssignValues(self, mach):
    """Assign values from local dict to vars accessible outside the class.

    I didn't want to access dictionaries external to the class, so this function
    does the work of providing values to all externally accessible variables
    that are assigned to dict mach.

    Args:
      mach: dict of machine values for this session.
    """

    self.arch = mach['arch']
    self.biosdate = mach['biosdate']
    self.build = mach['dist'] + ' ' + mach['code']
    self.cpu = mach['cpu']
    self.cpu_quantity = mach['cpu_quantity']
    self.kernel = mach['kernel']
    self.logname = '%s.%s.Log' % (mach['node'], self.logtype)
    self.memory = mach['memory']
    self.model = mach['model']
    self.name = '%s.%s.%s' % (self.logtype, mach['node'], mach['start'])
    self.serial = mach['serial']
    self.version = mach['version']
    if not self.description:
      self.description = self.model
    if not self.release:
      self.release = mach['release']

  def _SetMachineName(self, tokens, line):
    """Find and set the value for mach[key].

    Args:
      tokens: dictionary with values of identifier tokens.
      line: string, a line from a log file.
    Returns:
      key/value pair for mach[key].
    """

    valuedict = {}

    for key in tokens:
      if tokens[key] in line:
        if key == 'node':
          valuedict[key] = self._GetShortHostName(line)
        elif key == 'start':
          time = line.split(tokens[key])
          valuedict[key] = time[1].strip()
        else:
          valuedict[key] = self._GetSubString(line)

    return valuedict

  def _GetSubString(self, line, sep=':'):
    """Split a string using the sep character, returning a substring.

    Args:
      line: string, a line from a log.
      sep: character, to separate strings.
    Returns:
      a string, the value we care about.
    """

    sections = line.split(sep)
    if len(sections) < 2:
      self.logger.error('%s separator character not found!', sep)
      return line
    else:
      return sections[1].strip()

  def _IsTestResult(self, line, type):
    return self.LOG_KEYS[type][0] in line or self.LOG_KEYS[type][1] in line

  def _GetShortHostName(self, line):
    """Find and return the short host name.

    Args:
      line: string that contains the fully qualified domain name.
    Returns:
      string, the short host name.
    """

    node = self._GetSubString(line)
    fqdn = node.split('.')
    return fqdn[0]


def Usage():
  """Usage requirements and parameters.

  run specified job on a system under test.
  --help for parameter details.
  Required parameters:
  --config <pathname of yaml dictionary file>
  --job <job name> (string must match a job name in the yaml file)
  --op <config | get | halt | query | reboot | run | update>
  Optional parameters:
  --pubkey <filename> (required when op = config)
  --user <user_name> (run jobs as this user, must have correct permissions)
  """

  print Usage.__doc__
  sys.exit(1)


def main(argv):

  if len(argv) < 1:
    Usage()

  ra = RemoteAgent()
  if ra.options.op == 'run':
    if ra.options.job == 'all':
      for ra.job in ra.joblist:
        ra.RunJob()
        # tstatus = ra.SendReport()
        # if not tstatus:
        #   status = False
    else:
      ra.RunJob()
      # status = ra.SendReport()
  elif ra.options.op == 'get':
    if ra.job == 'ltp':
      ra.ltp_home = harness.GetLTPHome(ra.constants['ROOT'])
    # status = ra.SendReport()
  elif ra.options.op == 'query':
    ra.logger.info('This is the query operation')
  elif ra.options.op == 'config':
    ra.logger.info('Configuring host to run automated tests.')
    if ra.options.publickey:
      public_key = ra.options.publickey
    else:
      public_key = None
    if ra.Config(pubkey=public_key, user=ra.constants['ROLE']):
      ra.logger.info('Configuration completed')
  elif ra.options.op == 'clean':
    ra.logger.info('Cleaning %s on host.', ra.constants['ROOT'])
    if ra.Clean():
      ra.logger.info('Clean up completed.')


if __name__ == '__main__':
  main(sys.argv)
