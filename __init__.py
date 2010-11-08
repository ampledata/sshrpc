#!/usr/bin/env python2.6
# encoding: utf-8
"""SSHRPC - Module for setting up and controlling a host via SSH.

Usage
=====
    See help(SSHRPC)

History
=======
    * Based on SSHRPC from the Splunk Mambo package.
    * SSHRPC was created as a stripped down version of host.py
    * host.py was itself inherited from the autoperf package (dnorberg@splunk.com 2008)

Created by Greg Albrecht (gba@splunk.com).
Copyright 2010 Splunk, Inc. All rights reserved.
"""
__version__ = '$Id: //splunk/current/test/lib/sshrpc/__init__.py#2 $'
__author__  = '$Author: gba $'
__license__ = 'Copyright 2010 Splunk, Inc.'

import os
import sys
import logging
import datetime

from time import *
from glob import glob
from logging.handlers import *
from subprocess import Popen, PIPE

class SSHRPC(object):
    """Create and manage a SSH session to a (remote?) host.
        
    Description
    ===========
        When used this object will establish an SSH session to a host. Once the
        session is established methods within this object can be called that allow
        remote command execution, copying of files, and so on.
    
        
    Notes
    =====
        1. This class has been tested and is known to work on: Linux, Solaris, Mac OS X (Darwin),
        FreeBSD and AIX. Windows, via cygwin, has been tested, but not extensively.
        2. It is not necessary that the 'remote' host be remote at all, in fact, loopback
        support is easy:
    
        >>> import os, pwd
        >>> my_login = pwd.getpwuid(os.getuid())[0]
        >>> my_identity = os.path.join(os.path.expanduser('~'),'.ssh','id_dsa')
        >>> my_box = SSHRPC(host='localhost',login=my_login,identity=my_identity)
        >>> print my_box
        localhost
    
        3. To test this module with doctest try: python SSHRPC.py -v
        4. To test this module with py.test try: py.test mambo/tests/test_SSHRPC.py
        
    Example & Test
    ==============
        See also: method docstrings.
        >>> my_box = SSHRPC()
        >>> my_box
        localhost
        >>> my_box.execute(cmd='true')
        0
        >>> pipes = {}
        >>> my_box.execute(cmd='hostname',pipes=pipes)
        0
        >>> my_box.execute(cmd='echo hi',pipes=pipes)
        0
        >>> print pipes['stdout'].rstrip()
        hi
        
    Extending
    =========
        gba@20090520 It is my hope that only basic system commands be added as methods
        to SSHRPC. Dramatic remote system procedures, such as setting up or controlling
        software (like Splunk) should be written into sublcasses of SSHRPC.
        Please try to keep SSHRPC as stable and static as possible.
    """
    logger = logging.getLogger( 'SSHRPC' )
    logger.setLevel( logging.DEBUG )
    # console logger
    consoleLogger = logging.StreamHandler()
    consoleLoggerFormat = logging.Formatter( '%(levelname)s %(message)s' )
    consoleLogger.setFormatter( consoleLoggerFormat )
    consoleLogger.setLevel( logging.INFO )
    logger.addHandler( consoleLogger )
    # syslog logging
    sysLogger       = SysLogHandler( address=( 'esloghost.splunk.com', 514 ) )
    sysLoggerFormat = logging.Formatter( 'lineno=%(lineno)d %(levelname)s %(module)s %(funcName)s %(message)s' )
    sysLogger.setFormatter( sysLoggerFormat )
    sysLogger.setLevel( logging.DEBUG )
    logger.addHandler( sysLogger )
    # DEBUG file logging
    fileLogger       = logging.FileHandler( 'SSHRPC.debug_log', mode='wa' )
    fileLoggerFormat = logging.Formatter( '%(asctime)s lineno=%(lineno)d %(levelname)s %(module)s %(funcName)s %(message)s' )
    fileLogger.setFormatter( fileLoggerFormat )
    fileLogger.setLevel( logging.DEBUG )
    logger.addHandler( fileLogger )

    
    def __init__( self, host='localhost', login='', identity='', master=False ):
        # here's the important stuff
        if not login:       login    = self._find_username()
        if not identity:    identity = os.path.join( os.path.expanduser( '~' ), '.ssh', 'id_dsa' )
        self.host                    = host
        self.login                   = login
        self.identity                = identity
        self.master                  = master
        
        if not os.path.exists( self.identity ): raise Exception, "SSH identity %s does not exist." % self.identity
        
        self.logger.debug( "host=%s login=%s identity=%s master=%s" % (self.host,self.login,self.identity,self.master) )
        
        # to make sure we actually work we'll need to test our SSH version and attempt to connect
        self.ssh_args = self._setup_ssh()
        self.connect()
        
        # special sauce
        self.home = ''
        self.func_home()
        # if we can't determine our remote home we might as well give up
        if not self.home: raise Exception, "Cannot determine our home on %s" % self.host
        self.windows = False
        self.platform = {}
        self.py_platform = ''
        self.py_system = ''
        self.py_machine = ''
        self.func_platform()
        # determine linux distro
        self.distro = {}
        self.func_distro()
    
    
    def __repr__( self ):
        """Return the hostname as a representation of this object."""
        return self.host
    
    
    def __str__( self ):
        """Return the hostname if the object is referenced as a string."""
        return self.host
    
    
    def _exec( self, cmd, pipes=None, shell=False, timeout=0 ):
        """PRIVATE - Execute a command on a host.
        README: Do not call this function directly, instead use SSHRPC.execute().
        
        Test
        ====
            >>> my_box = SSHRPC()
            >>> my_box
            localhost
            >>> my_box.execute( 'sleep 11;echo hi', timeout=9) #doctest: +IGNORE_EXCEPTION_DETAIL
            Traceback (most recent call last):
            Exception: 'Command did not return 0.'
            >>> my_box.execute( 'sleep 7;echo hello', timeout=9)
            0
            >>>
        
        Operation
        =========
            @return: Output of Popen.wait(), and if pipes are passed, (dict) of stdout/stderr.
            @rtype: int + dict
            @param cmd: Command to run.
            @type cmd: string
            @param pipes: Populated with the STDOUT and STDERR from cmd.
            @type pipes: dict
            @param shell: TK
            @type shell: TK
        """
        self.logger.debug( "cmd=%s pipes=%s shell=%s timeout=%s" % (repr(cmd),pipes,shell,timeout) )
        start_time = datetime.datetime.now()
        # You may be tempted to make this "if not pipes"... don't.
        if pipes == None:
            try:
                po = Popen( cmd, shell=shell )
            except OSError as e:
                raise Exception, "OSError running command '%s':%s" % (cmd,e)
            except ValueError as e:
                raise Exception, "ValueError running command '%s':%s" % (cmd,e)
            except:
                raise Exception, "Unexpected error running command '%s':%s" % (cmd,sys.exc_info())
        else:
            try:
                po = Popen( cmd, stdout=PIPE, stderr=PIPE, shell=shell )
                pipes['stdout'], pipes['stderr'] = po.communicate()
                self.logger.debug( "pipes=%s" % (pipes) )
            except OSError as e:
                raise Exception, "OSError running command '%s':%s" % (cmd,e)
            except ValueError as e:
                raise Exception, "ValueError running command '%s':%s" % (cmd,e)
            except:
                raise Exception, "Unexpected error running command '%s':%s" % (cmd,sys.exc_info())
        if timeout > 0:
            return_code = po.poll()
            while return_code == None:
                return_code = po.poll()
                sleep( 0.2 )
                duration = ( datetime.datetime.now() - start_time ).seconds
                if duration > timeout:
                    self.logger.debug( "duration=%s > timeout=%s" % (duration,timeout) )
                    po.terminate()
                    return None
            return return_code
        else:
            return po.wait()
    
    
    def execute( self, cmd, dir='', pipes=None, env={}, ssh_args='', expected_return=0, timeout=0 ):
        """Execute a command on the remote host, return std[err|out] and exit code.
        Use this method instead of SSHRPC._exec().
        
        Returns: Depends.
        Required: cmd
          cmd=(str) The command to be run on the remote host.
        Optional: remote_dir,stdout,stderr,std,env,pipes, ssh_args,timeout
          remote_dir=(str) Directory to cd to before running cmd.
          timeout=(int) Number of seconds to wait for command to execute before terminating. (default = 0 (no timeout)
          ssh_args=(str) Extra flags to pass to this particular ssh command, separate
                             from the flags contained in self.ssh_args.
          others TK
        
        Test
        ====
            >>> my_box = SSHRPC()
            >>> my_pipes = {}
            >>> if my_box:
            ...     my_box.execute( "echo -n hi", pipes=my_pipes)
            0
            >>> if my_box:
            ...     my_pipes
            {'stderr': '', 'stdout': 'hi'}
            >>> if my_box:
            ...     my_box.execute( "tacoburritosalsa", pipes=my_pipes, expected_return=127 )
            127
            >>> if my_box:
            ...     my_pipes
            {'stderr': 'bash: tacoburritosalsa: command not found\\n', 'stdout': ''}
        
        """
        self.logger.debug( "cmd=%s dir=%s pipes=%s env=%s ssh_args=%s expected_return=%s timeout=%s " % (cmd, dir, pipes, repr( env ), ssh_args, expected_return, timeout) )
        vardeclarations = [ ( '%s=%s' % ( var, self.shesc( env[ var ] ) ) ) for var in env ]
        envdeclaration  = ' '.join( vardeclarations )
        if dir:
            cmd = 'cd %s && %s %s' % ( self.shesc( dir ), envdeclaration, cmd )
        else:
            cmd = '%s %s' % (envdeclaration, cmd)
        # build the ssh_cmd
        ssh_cmd = [ 'ssh' ]
        ssh_cmd.extend( self.ssh_args )
        ssh_cmd.extend( ssh_args )
        ssh_cmd.extend( [ self.host, cmd ] )
        result = self._exec( cmd=ssh_cmd, pipes=pipes, timeout=timeout )
        self.logger.debug( "result=%s" % (result) )
        if not result == expected_return:
            raise Exception, "Command did not return %s. result=%s ssh_cmd='%s'" % (expected_return,result,ssh_cmd)
        return result
    
    
    def _setup_ssh( self ):
        """PRIVATE - Detect ssh version and setup initial ssh_args for all methods.
        
        TODO: test every parameter before we return.
        
        Usage
        =====
        Returns: (list) An ordered list of ssh arguments on success, an empty list on failure.
        Required: n/a
        Optional: n/a
        
        Test
        ====
            >>> hl = SSHRPC()
            >>> hl
            localhost
            >>> if hl: True
            True
            >>> hl2 = SSHRPC(identity='tacoburritosalsa')
            Traceback (most recent call last):
            Exception: SSH identity tacoburritosalsa does not exist.
        
        """
        self.ssh_args = []
        _std = {}
        # This is a workaround for the "You don't exist, go away!" error on Mac OS X (Darwin)
        sessreg_cmd = ['/usr/X11/bin/sessreg','-w','/var/run/utmpx','-a',self.login + '\r']
        try:
            sessreg_exec = Popen( sessreg_cmd, stdout=PIPE, stderr=PIPE )
            _std['stdout'], _std['stderr'] = sessreg_exec.communicate()
            self.logger.debug( "%s returned %s" % (sessreg_cmd,_std) )
        except:
            self.logger.debug( "Not Fatal, don't worry... %s raised %s" % (sessreg_cmd,sys.exc_info()))
            pass
        # Setup our ssh_args, used across the board.
        self.ssh_args.extend( [ '-q', '-l', self.login , '-i' , self.identity] )
        self.ssh_args.extend( [ '-o', 'StrictHostKeyChecking=no', '-o', 'PreferredAuthentications=publickey' ] )
        # We're going to try to detect our SSH version as we're using some SSH features that aren't
        # available in all versions and they have different parameters in different versions.
        ssh_version_detect_cmd = [ 'ssh', '-V' ]
        try:
            ssh_version_detect_exec = Popen( ssh_version_detect_cmd, stdout=PIPE, stderr=PIPE )
            _std['stdout'], _std['stderr'] = ssh_version_detect_exec.communicate()
            self.logger.debug( "'%s' returned %s" % (ssh_version_detect_cmd,_std) )
        except OSError as e:
            raise Exception, "OSError running command '%s':%s" % (ssh_version_detect_cmd,e)
        except ValueError as e:
            raise Exception, "ValueError running command '%s':%s" % (ssh_version_detect_cmd,e)
        except:
            raise Exception, "Unexpected error running command '%s':%s" % (ssh_version_detect_cmd,sys.exc_info())
        if _std['stderr'].lower().find('openssh') > -1:
            if _std['stderr'].lower().find('debian') > -1:
                self.ssh_args.extend( [ '-o', 'SetupTimeOut=30', '-o', 'ServerAliveInterval=30' ] )
            else:
                # apparently only supported in openssh
                self.ssh_args.extend( [ '-o', 'ConnectTimeout=30' ] )
            # only openssh 4+ supports session caching
            if self.master and not _std['stderr'].lower().find('openssh_3') > -1:
                self.ssh_args.extend(['-S', os.path.join(os.path.expanduser('~'),'.ssh','master-%r@%h:%p')])
        else:
            self.master = False
        # this is here to print a runnable ssh command line to the debug log for testing
        _ssh_args = 'ssh'
        for _ssh_arg in self.ssh_args: _ssh_args = _ssh_args + " " + _ssh_arg
        self.logger.debug('_ssh_args="%s"' % (_ssh_args))
        return self.ssh_args
    
    
    def connect( self ):
        """Connect to the host via SSH.
        
        Usage
        =====
        Returns: (bool) True if the connection can be established, False if it can't.
        Required: n/a
        Optional: n/a
        
        Test
        ====
            >>> SSHRPC()
            localhost
            >>> SSHRPC().connect()
            True
        """
        test_ssh = [ 'ssh' ]
        test_ssh.extend( self.ssh_args )
        if self.master and self.ssh_args:
            # setup master ssh connection args
            test_ssh.extend( [ '-fnN', self.host ] )
            # gba@20090824 we're using 'yes' instead of 'auto' because we want to force any previous connection to flush
            if self.master: test_ssh.extend( [ '-o', 'ControlMaster=yes' ] )
        elif self.ssh_args:
            test_ssh.extend( [ self.host, 'true' ] )
        # gba@20090802 you may be tempted to pass _std as pipes here. don't do it, it will break the ssh session.
        if self._exec( cmd=test_ssh, pipes=None ) == 0: 
            return True
        else:
            return False
    
    
    def disconnect( self ):
        """Attempt to tear down (close) the ssh session to the (remote) host.
        TODO gba@20090605 add doctest.
        """
        _std = {}
        if self.master:
            ssh_teardown = [ 'ssh' ]
            ssh_teardown.extend( self.ssh_args )
            ssh_teardown.extend( [ '-o', 'ControlMaster=auto' ] )
            ssh_teardown.extend( [ '-fnN', '-O', 'exit', self.host ] )
            try:
                self._exec( cmd=ssh_teardown, pipes=_std )
            except:
                self.logger.debug( "Non-fatal unexpected error running command '%s': %s" % ( ssh_teardown, sys.exc_info() ) )
                raise
        self.logger.removeHandler( self.sysLogger )
        return True
    
    
    def __nonzero__( self ):
        """Wrapper for SSHRPC.connect()"""
        return self.connect()
    
    
    def __del__( self ):
        """Wrapper for SSHRPC.disconnect()"""
        self.logger.warn("SSHRPC teardown method called.")
        return self.disconnect()
    
    
    def shesc( self, rstr ):
        if rstr:
            return rstr.replace(' ','\ ')
        else:
            return ''
    
    
    def _find_username( self ):
        """
        Test
        ====
            >>> r = SSHRPC()
            >>> if r._find_username():
            ...     True
            True

        Operation
        =========
            @rtype: string
            @return: The local username.
        """
        # if we don't pass a username lets try to determine our local username
        if 'LOGNAME' in os.environ:
            username = os.environ['LOGNAME']
        elif 'USER' in os.environ:
            username = os.environ['USER']
        elif 'LOGNAME' in os.environ:
            username = os.environ['LOGNAME']
        else:
            try:
                import pwd
                username = pwd.getpwuid(os.getuid())[0]
            except Exception, e:
                pass
        return username
    
    
    def uname( self, options='-a' ):
        """Get the uname of the remote system.
        If called without any options will return the full (uname -a) output.
        
        Returns: (str) The uname output on success, empty string on failure.
        Required: n/a
        Optional: options
            options: (str) list of options to pass to remote uname (default = '-a')
        
        Example & Test
        ==============
        >>> my_box = SSHRPC()
        >>> if my_box:
        ...     if my_box.uname(): True
        True
        >>> if my_box:
        ...     if my_box.uname(options='-s'): True
        True
        
        """
        self.logger.debug( "options=%s" % (options) )
        _return = ''
        _std = {}
        if self.execute( cmd='uname %s' % (options), pipes=_std) == 0:
            _return = _std['stdout'].rstrip()
        self.logger.debug( "_return=%s" % (_return) )
        return _return
    
    
    def func_distro( self ):
        """Get the lsb_release distro name.
        This method is only useful for discovering Linux distribution types, otherwise
        it will return a mostly useless dictionary.
        
        Returns: (dict) Dictionary of lsb_release parameters on success, empty dict on fail.
            e.g: Success={'linux':'', 'description':'', 'release':''}
            e.g: Fail={}
        Required: n/a
        Optional: n/a
        """
        if not 'linux' in self.distro and 'hostOS' in self.platform and self.platform['hostOS'].lower().find("linux") > -1:
            _std = {}
            if self.execute(cmd="lsb_release -d",pipes=_std) == 0: 
                self.distro['description'] = _std['stdout'].rstrip().split('Description:\t')[-1]
            if self.execute(cmd="lsb_release -r",pipes=_std) == 0: 
                self.distro['release'] = _std['stdout'].rstrip().split('Release:\t')[-1]
            if self.execute(cmd="[ -f /etc/debian_version ]") == 0:
                self.distro['linux'] = 'debian'
            elif self.execute(cmd="[ -f /etc/redhat-release ]") == 0:
                self.distro['linux'] = 'redhat'
        self.logger.debug("self.distro=%s" % (self.distro))
        return self.distro
    
    
    def func_platform( self ):
        """Get the OS and Architecture of the remote system.
        
        Returns: (dict) Dictionary of OS and Architecture on success, empty dictionary on failure.
          e.g.: Success={'hostOS':'','hostArch':''}
          e.g.: Fail={}
        Required: n/a
        Optional: n/a
        
        Example & Test
        ==============
        >>> my_box = SSHRPC()
        >>> if my_box:
        ...     if my_box.func_platform(): True
        True
        >>> if my_box:
        ...     if my_box.func_platform()['hostOS']: True
        True
        >>> if my_box:
        ...     if my_box.func_platform()['hostArch']: True
        True
        >>> if my_box:
        ...     if my_box.func_platform()['hostOS'] == my_box.uname('-s'): True
        True
        >>> if my_box:
        ...     if 'hostOS' in my_box.platform: True
        True
        
        """
        if not 'hostOS' in self.platform and not 'hostArch' in self.platform:
            _std = {}
            self.platform = {'hostOS': self.uname('-s'),'hostArch': self.uname('-p')}
            # some systems differentiate between 'architecture' and 'machine'
            # gentoo returns 'Intel(R) Core(TM)2 Quad CPU Q9450 @ 2.66GHz' for '-p' (on some systems)
            if self.platform['hostArch'] == "unknown" or not self.platform['hostArch'] or self.platform['hostArch'].find('Intel(R)') > -1:
                self.platform['hostArch'] = self.uname('-m')
            # sunos needs a little more love
            if self.platform['hostOS'] == "SunOS" and self.platform['hostArch'] == "i386":
                if self.execute( cmd='/usr/bin/isainfo -k', pipes=_std ) == 0:
                    self.platform['hostArch'] = _std['stdout'].rstrip()
            # lets globally say we're windows
            if self.platform['hostOS'].lower().find('cygwin') > -1:
                self.windows = True
        
        # new school stuff follows
        _std = {}
        self.execute( cmd="python -m platform", pipes=_std)
        self.py_platform = _std['stdout'].rstrip()
        (ret, _std) = self.python( program="import platform;print platform.system()" )
        self.py_system = _std['stdout'].rstrip()
        (ret, _std) = self.python( program="import platform;print platform.machine()" )
        self.py_machine = _std['stdout'].rstrip()
        
        self.logger.debug("self.windows=%s self.platform=%s" % (self.windows,self.platform,))
        return self.platform
    
    
    def rsync( self, local, remote='', reverse=False ):
        """Sync the contents of the local to remote using rsync
        or from remote to local if reverse=True.
        
        Usage
        =====
        Returns: (bool) True on success, False on failure.
        Required: local
            local: (str) Full or relative path to the file or directories to be rsync'd.
        Optional: remote
            remote: (str) Full or relative path to the destination directory. (default='')
            reverse: (bool) if false syncs from local to remote, if true, syncs from remote to local
        
        Notes
        =====
        1. If syncing from local to remote, remote will be created as a directory, if it does not already exist.
        2. If syncing from remote to local, local will be created as a directory, if it does not already exist
        3. to copy the contents of a dir, append the dir with a slash '/'
        
        Example
        =======
        A. This will copy /etc/hosts from the local machine to /usr/local/etc/hosts on the remote machine.
            SSHRPC.rsync(local='/etc/hosts',remote='/usr/local/etc')
        B. This will copy /etc/local/etc/hosts from the remote machine to /etc/hosts on the local machine (reverse of the above command)
            SSHRPC.rsync(local='/etc', remote='/usr/local/etc/hosts', reverse=True)
        
        Test
        ====
            >>> from random import choice
            >>> random_dir_name = ''.join([choice('doctest0123456789') for i in range(8)])
            >>> my_box = SSHRPC()
            >>> my_box.rsync( local='/etc/resolv.conf', remote=random_dir_name )
            True
            >>> my_box.path_exists( my_box.path_join( random_dir_name, 'resolv.conf' ) )
            True
            >>> my_box.rsync( local=random_dir_name, remote=os.path.join(random_dir_name, 'resolv.conf'), reverse=True )
            True
            >>> os.path.exists( os.path.join( random_dir_name, 'resolv.conf' ) )
            True
        """
        self.logger.debug( "local=%s remote=%s reverse=%s" % (local,remote,reverse) )
        _return = False
        rsync_cmd = [ 'rsync', '-qar',  '--rsync-path=rsync' ]
        rsync_cmd.extend( [ '-e', 'ssh %s' % " ".join( self.ssh_args ) ] )
        local_path = self.shesc( os.path.expanduser( local ) )
        if remote:
            remote = self.shesc( remote )
        if reverse:
            if not os.path.exists( local_path ):
                os.makedirs( os.path.abspath( local_path ) )
            rsync_cmd.extend( [ ':'.join( ( self.host, remote ) ) ] )
            rsync_cmd.extend( [ local_path ] )
        else:
            self.execute( cmd='mkdir -p %s' % remote, pipes={} )
            rsync_cmd.extend( [ local_path ] )
            rsync_cmd.extend( [ ':'.join( ( self.host, remote ) ) ] )
        self.logger.debug( "rsync_cmd=%s" % (rsync_cmd) )
        if self._exec( rsync_cmd ) == 0: _return = True
        self.logger.debug( "_return=%s" % (_return) )
        return _return
    
    
    def func_home( self ):
        """Get our home directory on the system and set self.home to this dir.
        
        Test
        ====
            >>> my_box = SSHRPC()
            >>> if my_box.func_home(): True
            True
            >>> if my_box.home: True
            True
        
        Operation
        =========
            @return: Home directory on success, empty string on failure.
            @rtype: string
        """
        if self.home:
            return self.home
        else:
            _std = {}
            if self.execute( '[ -d $HOME ] && echo $HOME', pipes=_std ) == 0 and _std['stdout']:
                self.home = _std['stdout'].rstrip()
        self.logger.debug( "self.home=%s" % (self.home,) )
        return self.home
    
        
    def python( self, program ):
        _std = {}
        returnCode = self.execute( cmd='python -c "import os,sys;%s"' % program, pipes=_std )
        return ( returnCode, _std )
    
    
    def path_exists( self, path ):
        return eval(self.python( "print os.path.exists( '%s' )" % path )[1]['stdout'].rstrip())
    
    
    def path_join( self, *args ):
        # this was a lot harder to figure out than it looks...
        return self.python( "print os.path.join( '%s' )" % "','".join( args ) )[1]['stdout'].rstrip()
    
    
    def path_abspath( self, path ):
        return self.python( "print os.path.abspath( '%s' )" % path )[1]['stdout'].rstrip()
    

    def file_copy( self, src, dest ):
        if self.execute( cmd="cp %s %s" % (src,dest), pipes={} ) == 0:
            return True
        else:
            return False
    
    
    def file_retrieve( self, source, dest ):
        import tempfile
        import urllib
        fileName    = source.split('/')[-1]
        tmpDir      = tempfile.mkdtemp()
        tmpFile     = os.path.join( tmpDir, fileName )
        urllib.urlretrieve( source, tmpFile )
        self.rsync( local=tmpFile, remote=dest )
        remoteFile = self.path_join( dest, fileName )
        if not self.path_exists( remoteFile ):
            raise Exception, "Destination file %s doesn't exist on %s" % (finalDest,self.host)
        return remoteFile
    

if __name__ == "__main__":
    import doctest
    doctest.testmod()
