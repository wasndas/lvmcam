# @Author: Mingyu Jeon (mgjeon@khu.ac.kr)
# @Date: 2021-08-23
# @Filename: expose.py

from __future__ import absolute_import, annotations, division, print_function
import click
from click.decorators import command
from clu.command import Command
from lvmcam.actor.commands import parser

from lvmcam.actor.commands.connection import camdict
import lvmcam.actor.commands.camstatus as camstatus

__all__ = ["expose"]

import asyncio
import os
from araviscam.araviscam import BlackflyCam as blc

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

# import basecam

# from basecam.exposure import ImageNamer
# image_namer = ImageNamer(
#     "{camera.name}-{num:04d}.fits",
#     dirname=".",
#     overwrite=False,
# )

import datetime

def pretty(time):
    return f"{bcolors.OKCYAN}{bcolors.BOLD}{time}{bcolors.ENDC}"

import functools

@parser.command()
@click.argument("EXPTIME", type=float)
@click.argument('NUM', type=int)
@click.argument('CAMNAME', type=str)
@click.argument("FILEPATH", type=str, default="python/lvmcam/assets")
async def expose(
    command: Command,
    exptime: float,
    num: int,
    camname: str,
    filepath: str,
):
    """
    Do 'EXPTIME' expose 'NUM' times by using 'CAMNAME' camera.
    """
    print(f"{pretty(datetime.datetime.now())} | lvmcam/expose.py | expose function start")
    if(not camdict):
        command.error(error="There are no connected cameras")
        return
    cam = camdict[camname]
    camera, device = camstatus.get_camera()
    exps = []
    status = []
    for i in range(num):
        print(f"{pretty(datetime.datetime.now())} | lvmcam/expose.py | #{i+1}, EXP={exptime}, Expose start")
        exps.append(await cam.expose(exptime=exptime, image_type="object"))
        status.append(await camstatus.custom_status(camera, device))
        # await cam.expose(exptime=exptime, filename=paths[i], write=True)
        print(f"{pretty(datetime.datetime.now())} | lvmcam/expose.py | #{i+1}, EXP={exptime}, Expose done")
    
    # print(status)
    hdus = []
    dates = []
    for i in range(num):
        print(f"{pretty(datetime.datetime.now())} | lvmcam/expose.py | #{i+1}, EXP={exptime}, Setting header start")
        hdu = exps[i].to_hdu()[0]
        # print(hdu.header['DATE-OBS'])
        # hdus.append(hdu)
        # print(repr(hdu.header))
        # print("")
        dates.append(hdu.header['DATE-OBS'])
        # hdu.header['TEST'] = "TEST"
        # print(repr(hdu.header))
        # print("")
        for item in list(status[i].items()):
            hdr = item[0] 
            val = item[1]
            # print(hdr, len(val))
            if len(val) > 70:
                continue
            _hdr = hdr.replace(" ", "")
            _hdr = _hdr.replace(".", "")
            _hdr = _hdr.upper()[:8]
            hdu.header[_hdr] = (val, hdr)
        # print(repr(hdu.header))
        hdus.append(hdu)
        print(f"{pretty(datetime.datetime.now())} | lvmcam/expose.py | #{i+1}, EXP={exptime}, Setting header done")

    # for hdu in hdus: print(repr(hdu.header))

    print(f"{pretty(datetime.datetime.now())} | lvmcam/expose.py | Making filename start")
    filepath = os.path.abspath(filepath)
    paths = []
    for i in range(num):
        filename = f'{cam.name}-{dates[i]}.fits'
        paths.append(os.path.join(filepath, filename))
        print(f"{pretty(datetime.datetime.now())} | lvmcam/expose.py | Ready for {paths[i]}")
        print(f"{pretty(datetime.datetime.now())} | lvmcam/expose.py | Write start")
        writeto_partial = functools.partial(
            hdus[i].writeto, paths[i], checksum=True
        )
        # hdus[i].writeto(paths[i])
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, writeto_partial)
        print(f"{pretty(datetime.datetime.now())} | lvmcam/expose.py | Write done")
    print(f"{pretty(datetime.datetime.now())} | lvmcam/expose.py | Making filename done")
    # for hdu in hdus: print(repr(hdu.header))


    # print(con.cam.name)
    # date_obs = hdus[0].header['DATE-OBS']
    # print(date_obs)
    # for i in range(num)
    # await cs.remove_camera(uid=cam.name)
    command.finish(path=paths)
    print(f"{pretty(datetime.datetime.now())} | lvmcam/expose.py | expose function done")
    return
