# send notfications through irssinotifier to android
import sys
import traceback
from subprocess import Popen, PIPE
import string
import shlex
import znc
import requests


def _is_self(*args):
    """Utility method to make sure only calling on right modules."""
    if len(args) > 1 and type(args[0]) == irssinotify:
        return args[0]
    return None


def trace(fn):
    """Useful decorator for debugging."""
    def wrapper(*args, **kwargs):
        s = _is_self(*args)
        if s:
            s.PutModule("TRACE: %s" % (fn.__name__))
        return fn(*args, **kwargs)
    return wrapper


def catchfail(fn):
    """Catch exceptions and get them onto the module channel."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            s = _is_self(*args)
            if s:
                s.PutModule("Failed with %s" % (e))
                # then get the whole stack trace out
                lines = traceback.format_exception(exc_type, exc_value,
                                                   exc_traceback)
                for line in lines:
                    s.PutModule(line)
    return wrapper


class mailonmsgtimer(znc.Timer):
    nick = None
    chan = None
    mod = None

    def RunJob(self):
        if self.mod.send_email(self.nick, self.chan):
            self.mod.PutModule("clearing buffer")
            self.mod.clear_buffer(self.nick, self.chan)
            self.mod.PutModule("Email sent")


class irssinotify(znc.Module):
    description = "IrssiNotifier plugin for ZNC"
    module_types = [znc.CModInfo.UserModule]

    def _should_send(self, nick, chan=None, msg=""):
        """Conditions on which we should send a notification."""
        if not self.GetNetwork().IsIRCAway():
            self.PutModule("Not sending because not away")
            return False
        else:
            return True

    def _highlight(self, msg):
        if msg.find(self.GetNetwork().GetCurNick()) != -1:
            return True

        for word in self.keywords:
            if msg.find(word) != -1:
                return True

        return False

    def buffer(self, nick, chan):
        key = "%s:%s" % (nick, chan)
        if key in self.pending:
            return self.pending[key]
        else:
            return None

    def create_buffer(self, nick, chan):
        self.pending["%s:%s" % (nick, chan)] = ""

    def clear_buffer(self, nick, chan):
        key = "%s:%s" % (nick, chan)
        del self.pending[key]

    def add_to_buffer(self, nick, chan, msg):
        key = "%s:%s" % (nick, chan)
        cur = self.pending[key]
        self.pending[key] = cur + "\n" + msg

    @catchfail
    def send(self, nick, chan=None, msg=""):
        if not self._should_send(nick=nick, chan=chan, msg=msg):
            return False

        if self.buffer(nick, chan) is None:
            self.create_buffer(nick, chan)
            timer = self.CreateTimer(mailonmsgtimer, interval=60, cycles=1)
            timer.mod = self
            timer.nick = nick
            timer.chan = chan

        self.add_to_buffer(nick, chan, msg)

    @catchfail
    def send_email(self, nick, chan):
        msg = self.buffer(nick, chan)
        if not msg:
            self.PutModule("Something is wrong, no message")
            return False

        url = "https://irssinotifier.appspot.com/API/Message"
        payload = {'apiToken': self.nv['token'],
                   'nick': self._encrypt(nick),
                   'channel': self._encrypt(chan),
                   'message': self._encrypt(msg),
                   'version': 13}
        resp = requests.get(url, params=payload)

        return True

    @catchfail
    @trace
    def OnStatusCommand(self, cmd):
        print("STATUS: %s" % cmd)
        return znc.CONTINUE

    def OnLoad(self, args, msg):
        self.keywords = [
            self.GetUser().GetNick()
            ]

        arglist = args.split()
        for arg in arglist:
            k, v = arg.split("=")
            if k in ('key', 'token'):
                self.nv[k] = v

        fail = False
        if 'key' not in self.nv:
            self.PutModule("No key specified, please pass key=encrkey "
                           "to the loadmod call")
            fail = True
        if 'token' not in self.nv:
            self.PutModule("No token specified, please pass token=apitoken "
                           "to the loadmod call")
            fail = True

        if fail:
            return False
        else:
            self.PutModule("irssinotify loaded successfully")
            return znc.CONTINUE

    @catchfail
    def OnPrivMsg(self, nick, msg):
        # self.PutModule("PRIVMSG received from %s" % nick.GetNick())
        self.send(nick=nick.GetNick(), msg=msg.s)
        return znc.CONTINUE

    @catchfail
    def OnChanMsg(self, nick, channel, msg):
        if self._highlight(msg.s):
            self.send(nick=nick.GetNick(), chan=channel.GetName(),
                      msg=msg.s)
        return znc.CONTINUE

    @catchfail
    def GetWebMenuTitle(self):
        return "E-Mail on messages when away"

    def _encrypt(self, text):
        cmd = "openssl enc -aes-128-cbc -salt -base64 -A -pass pass:%s" % (self.nv['key'])
        output, errors = Popen(shlex.split(cmd), stdin=PIPE, stdout=PIPE, stderr=PIPE).communicate(text+" ")
        output = string.replace(output, "/", "_")
        output = string.replace(output, "+", "-")
        output = string.replace(output, "=", "")
        return output
