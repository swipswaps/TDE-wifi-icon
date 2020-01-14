#!/usr/bin/python3

"""
    Systray icon showing wifi signal strength on remote device (wifi repeater etc)

    Designed for TDE (whch is Qt3 based), but implemented for Qt5 as Qt3 (TQt) is missing QSystemTrayIcon class

    It periodically queries the remote device (wifi client/bridge/repeater) dd-wrt info page (no login/pass required)
    and extracts access point status line. Based on preconfig table signal_level->icon is renders system-tray
    icon to visualise connection status. The tooltip shows more details. Right-click menu supports forced refresh and exit.

    link to ~/.trinity/Autostart/ for autostart

    Note: QSound is not working (broken ?) - so no audible notifications for now

    Note: There are intermittent artifacts on nvidia-340 xorg drivers.

    TODO: debug why QSound() is not working
    TODO: read consfig from ini
    TODO: eliminate artifacts on nvidia drovers
    TODO: open minimalistic web browser with dd-wrt info page from right-click menu entry
    TODO: store long term statistics and provide visualization

"""

import sys, os, re

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QSystemTrayIcon, QApplication, QMenu, QStyle
from PyQt5.QtGui import QIcon
from PyQt5.QtMultimedia import QSound
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

DBG = 0

def dbg_print(str):
    """ quick-&-dirty debug helper (output to stdout) """
    if DBG: print(str)


class SystemTrayIcon(QSystemTrayIcon):
    """ system tray icon showing wifi signal strength on remore device """

    def __init__(self, icon, parent=None):
        """ init"""
        # parent
        super().__init__(icon, parent)
        # empty icon (trying to eliminate visible artifacts on nvidia-340, but is doesnt work all the time)
        #self.setIcon(QIcon())
        # menu - exit
        self.menu = QMenu()
        exitAction = self.menu.addAction("Exit")
        exitAction.triggered.connect(self.exit)
        # menu refresh
        refreshAction = self.menu.addAction("Refresh")
        refreshAction.triggered.connect(self.update)
        #
        self.setContextMenu(self.menu)
        #
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)

    def exit(self):
        """ exit has been pressed """
        QApplication.quit()

    def autoupdate(self, sec=60):
        """ refresh icon every sec seconds """
        self.update()
        self.show()
        self.timer.start(sec * 1000)

    def _load_icon(self, dir, name, ext='.png'):
        """ load resources - icons from dir identified by name with extension ext """
        path = '/'.join([dir, name + ext])
        return QIcon(path) if os.path.exists(path) else None

    def _load_sound(self, dir, name, ext=['.ogg', '.mp3', '.wav']):
        """ load resources - sound file from dir identified by name, try ext extensions (the first wins) """
        dirname = '/'.join([dir, name])
        for e in ext:
            path = dirname + e
            if os.path.exists(path):
                return QSound(path)
        return None

    def cfg_signal_table(self, levelstr, dir, ext='.png', sep=':,'):
        """ build configurable signal table - signal_level:icon_name, ... from string from config file """
        self.signal = []
        for lvl_txt in levelstr.strip().split(sep[1]):
            level, txt = lvl_txt.strip().split(sep[0])
            level, txt = level.strip(), txt.strip()
            item = {
                # numeric level Q10 (Q*10)
                'level': int(level),
                # signal description - low, medium, high, error
                'signal': txt,
                # preloaded icon resource
                'icon':  self._load_icon(dir, txt),
                # preloaded audible notification
                'sound': self._load_sound(dir, txt)
            }
            self.signal.append(item)
            dbg_print('cfg_signal_table() lvl_txt=%s item=%s' % (lvl_txt, item))
        return

    def get_entry_for_level(self, level):
        """ get signal table entry for signal level """
        entry = None
        for tab in self.signal:
            if level < tab['level']: break
            entry = tab
        dbg_print('get_entry_for_level(%d) -> %s' % (level, entry))
        return entry

    def get_icon_for_signal(self, txt):
        """ get icon for signal text txt (used for error when level is not available) """
        return [ i['icon'] for i in self.signal if i['signal'] == txt ][0]

    def cfg_device(self, device):
        """ configure device to monitor """
        self.device = device

    def check_device(self, device):
        """ get data from monitored (remote) device """
        res = {
            'signal': 'error',
            'desc': '?'
        }
        try:
            #                          MAC           if    uutime     Tx    Rx   signal noise SNR Q10
            # setWirelessTable('00:26:18:85:25:87','eth1','0:28:11','39M','78M','-57','-79','22','453');
            for line in urlopen(device['url'], timeout=device['timeout']).readlines():
                m = re.search(device['regex'], line.decode('utf-8'))
                if m:
                    return m.groupdict()
            res = {
                'signal': 'nocon',
                'desc': device['no_wifi']
            }
        except HTTPError as e:
            res['desc'] = device['http_error'] % { 'errno': e.code, 'strerror': e.reason }
        except URLError as e:
            res['desc'] = device['url_error'] % { 'errno': e.reason.errno, 'strerror': e.reason.strerror }
        return res

    def callculate(self, d):
        """ calculate Q, SN fields """
        if d.get('Q10'):
            d['Q'] = int(d['Q10']) // 10
            d['SN'] = int(d['signal']) - int(d['noise'])
        return d

    def update(self):
        """ query the remote device and update systray icon """
        # remote device or test data if provided
        res = self.test_data() if hasattr(self, 'data') else self.check_device(self.device)
        if DBG: print('update() res=%s' % res)
        # if ok (got Q10)
        if res.get('Q10'):
            # valid data {Q10: 123, SNR: 30, signal:-54, noise:-88} so calculate Q,SN fields
            res = self.callculate(res)
            tooltip = self.device['tooltip'] % res
            entry = self.get_entry_for_level(res[self.device['tab_key']])
            #self.play_sound(entry['sound'])
            icon = entry['icon']
        else:
            # error 'signal':'nocon', 'desc':description
            icon = self.get_icon_for_signal(res['signal'])
            tooltip = self.device['tooltip_error'] % res
        # update icon and tooiltip
        dbg_print('update() icon=%s tooltip=%s' % (icon, tooltip))
        self.setIcon(icon)
        self.setToolTip(tooltip)

    def play_sound(self, sound):
        """ audible notification """
        if sound: sound.play()

    def test_data(self, data=None):
        """ diagnostic data for self-test """
        # initiate data if provided
        if data:
            self.data, self.data_idx = data, 0
            return
        # get actual entry
        d = self.data[self.data_idx]
        # next in round-robin fasion
        self.data_idx = (self.data_idx + 1) % len(self.data)
        # return diag entry
        return d


def main(app):
    """ main - instatiate app, read/process config and execute """

    # default icon
    style = app.style()
    #icon = QIcon(style.standardPixmap(QStyle.SP_ComputerIcon))
    icon = QIcon(style.standardPixmap(QStyle.SP_BrowserStop))
    wifiIcon = SystemTrayIcon(icon, app)

    # config
    app_dir = os.path.dirname(sys.argv[0])

    # signal table
    #
    # signal_level:icon_name - signal_level can be Q,Q10,SNR,SN based on tab_key
    # negative numbers are for error conditions so they can be arbitrary negative number
    # entries are trimmed so any whitespaces are removed before processing
    wifiIcon.cfg_signal_table('-2:error, -1:nocon, 0:low, 16:medium, 35:high', app_dir + '/icon/128')

    # remote device config
    #
    device = {
        # device to check
        'url': 'http://192.168.1.3',
        # dd-wrt r22000++ king-kong
        #'regex': r"setWirelessTable\('(?P<MAC>.+)',"
        #         r"'(?P<if>.+)','(?P<uptime>.+)','(?P<TXrate>.+)','(?P<RXrate>.+)',"
        #         r"'(?P<signal>.+)','(?P<noise>.+)','(?P<SNR>\d+)','(?P<Q10>\d+)'\);",
        # dd-wrt r41328
        'regex': r"setWirelessTable\('(?P<MAC>.+)',"
                 r"'(?P<rname>.*)','(?P<if>.+)','(?P<uptime>.+)','(?P<TXrate>.+)','(?P<RXrate>.+)',"
                 r"'(?P<info>.+)','(?P<signal>.+)','(?P<noise>.+)','(?P<SNR>\d+)','(?P<Q10>\d+)'\);",
        # connect timeout
        'timeout': 3,
        # key for signal table - one of Q, Q10, SNR, SN
        'tab_key': 'Q',
        # ok tooltip
        'tooltip': "SNR: %(SNR)s / SN: %(SN)d / Q: %(Q)d%%",
        # error tooltip
        'tooltip_error': 'ERR: %(desc)s',
        # error message - no wifi connection to AP
        'no_wifi': 'no wifi connection',
        # error message - http error - supported keys: errno, strerror
        'http_error': 'http %(strerror)s',
        # error message - url error - supported keys: errno, strerror
        'url_error':  'url %(strerror)s',
    }
    wifiIcon.cfg_device(device)

    # execute diagnostic test without quering remote device
    tdata = [
        {'signal': 'error', 'desc': 'connection timeout'},
        {'signal': 'nocon', 'desc': 'no wifi connection'},
        {'Q10': '0',   'SNR': '-5', 'signal':'-100', 'noise':'-95'},
        {'Q10': '150', 'SNR': '5', 'signal':'-95', 'noise':'-100'},
        {'Q10': '160', 'SNR': '15', 'signal':'-85', 'noise':'-100'},
        {'Q10': '350', 'SNR': '25', 'signal':'-75', 'noise':'-100'},
        {'Q10': '360', 'SNR': '35', 'signal':'-65', 'noise':'-100'},
        {'Q10': '1000', 'SNR': '55', 'signal':'-45', 'noise':'-100'}
    ]
    #wifiIcon.test_data(tdata)

    # run periodic updates every ...
    wifiIcon.autoupdate(60)

    # execute loop
    return app.exec_()

# MAIN
#
if __name__ == '__main__':

    # application
    app = QApplication(sys.argv[1:])
    main(app)
