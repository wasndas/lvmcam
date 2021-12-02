from __future__ import absolute_import, annotations, division, print_function

import asyncio
import datetime
import functools
import os
import shutil

import click
import numpy as np
import astropy
from astropy.io import fits
from astropy.time import Time
from click.decorators import command
from clu.command import Command

from lvmcam.actor import modules
from basecam.actor.commands import camera_parser as parser
from lvmcam.actor.commands import connection
from lvmcam.araviscam import BlackflyCam as blc
from lvmcam.flir import FLIR_Utils as flir
import basecam.exposure as base_exp

__all__ = ["expose"]


@parser.command()
@click.option("-t", "--testshot", is_flag=True)
@click.option("-v", "--verbose", is_flag=True)
# compression option
@click.option(
    "-c",
    "--compress",
    type=click.Choice(["r", "h", "rF", "rD", "hF", "hD"], case_sensitive=True),
)
@click.option("-p", "--filepath", type=str, default="python/lvmcam/assets")
# right ascension in degrees
@click.option("-r", "--ra")
# declination in degrees
@click.option("-d", "--dec")
# K-mirror angle in degrees
# Note this is only relevant for 3 of the 4 tables/telescopes
@click.option("-K", "--kmirr", type=float, default=0.0)
# focal length of telescope in mm
# Default is the LCO triple lens configuration of 1.8 meters
@click.option("-f", "--flen", type=float, default=1839.8)
@click.argument("EXPTIME", type=float)
@click.argument("NUM", type=int)
# the last argument is mandatory: must be the name of exactly one camera
# as used in the configuration file
@click.argument("CAMNAME", type=str)
async def expose(
    command: Command,
    testshot: bool,
    verbose: bool,
    filepath: str,
    ra: float,
    dec: float,
    kmirr: float,
    flen: float,
    exptime: float,
    num: int,
    camname: str,
    compress: click.Choice,
):
    """
    Expose ``num`` times and write the images to a FITS file.

    Parameters
    ----------
    testshot
        Test shot on or off
    verbose
        Verbosity on or off
    filepath
        The path to save the images captured by the camera
    ra
        RA J2000 in degrees or in xxhxxmxxs format
    dec
        DEC J2000 in degrees or in +-xxdxxmxxs format
    kmirr
        Kmirr angle in degrees (0 if up, positive with right hand rule along North on bench)
    flen
        focal length of telescope/siderostat in mm
        If not provided it will be taken from the configuration file
    exptime
        The exposure time in seconds. Non-negative.
    num
        The number of exposure times. Natural number.
    camname
        The name of camera to expose.
    compress
        The option of fpack (FITS image compression programs).
        (-c r == fpack -r)
        (-c h == fpack -h)
        (-c rF == fpack -r -F)
        (-c rD == fpack -r -D)
        (-c hF == fpack -h -F)
        (-c hD == fpack -h -D)
    """
    if not connection.camdict:
        return command.error("There are no connected cameras")

    modules.change_dir_for_normal_actor_start(__file__)

    if verbose:
        modules.logger.sh.setLevel(int(verbose))
    else:
        modules.logger.sh.setLevel(modules.logging.WARNING)

    cam = connection.camdict[camname]

    targ = make_targ_from_ra_dec(ra, dec)

    if testshot:
        num = 1

    if cam.name == "test":
        filepath, paths = await expose_test_cam(testshot, exptime, num, filepath, cam)
        # for path in paths:
        #     command.write("i", f"{path}")
        path_dict = {i: paths[i] for i in range(len(paths))}
        command.info(PATH=path_dict)
        return command.finish()
    else:
        paths = await expose_real_cam(
            testshot,
            exptime,
            num,
            targ,
            kmirr,
            filepath,
            camname,
            cam,
            flen,
            compress,
        )
        # for path in paths:
        #     command.write("i", f"{path}")
        path_dict = {i: paths[i] for i in range(len(paths))}
        command.info(PATH=path_dict)
        return command.finish()


# @modules.timeit
def make_targ_from_ra_dec(ra, dec):
    if ra is not None and dec is not None:
        if ra.find("h") < 0:
            # apparently simple floating point representation
            targ = astropy.coordinates.SkyCoord(
                ra=float(ra), dec=float(dec), unit="deg"
            )
        else:
            targ = astropy.coordinates.SkyCoord(ra + " " + dec)
    else:
        targ = None
    return targ


# @modules.timeit
def get_last_exposure(path):
    try:
        with open(path, "r") as f:
            return int(f.readline())
    except FileNotFoundError:
        dirname = os.path.dirname(path)
        os.makedirs(dirname, exist_ok=True)
        with open(path, "w") as f:
            f.write("0")
            return 0


# @modules.timeit
def set_last_exposure(path, num):
    with open(path, "w") as f:
        f.write(str(num))


# @modules.timeit
def time_to_jd(times):
    # times = ["2021-09-07T03:14:43.060", "2021-09-07T04:14:43.060", "2021-09-08T03:14:43.060"]
    t = Time(times, format="isot", scale="utc")
    jd = np.array(np.floor(t.to_value("jd")), dtype=int)
    return jd


# @modules.timeit
def jd_to_folder(path, jd):
    jd = set(jd)
    for j in jd:
        filepath = os.path.abspath(os.path.join(path, str(j)))
        try:
            os.makedirs(filepath)
        except FileExistsError:
            pass


@modules.atimeit
async def expose_real_cam(
    testshot,
    exptime,
    num,
    targ,
    kmirr,
    filepath,
    camname,
    cam,
    flen,
    compress,
):

    exps, hdrs, status, camera = await expose_cam(exptime, num, cam, camname)
    status[0].update(await flir.status_for_header(camera))
    # print(status)

    hdus, dates = make_header_info(num, targ, kmirr, camname, exps, hdrs, status, flen)

    paths = await make_file(
        testshot,
        num,
        filepath,
        cam,
        hdus,
        dates,
        compress,
    )

    return paths


@modules.atimeit
async def make_file(
    testshot,
    num,
    filepath,
    cam,
    hdus,
    dates,
    compress,
):
    configfile, curNum, paths = prepare_write_file(
        testshot, num, filepath, cam, hdus, dates
    )
    await write_file(
        testshot,
        num,
        hdus,
        configfile,
        curNum,
        paths,
        compress,
    )
    return paths


@modules.timeit
def prepare_write_file(testshot, num, filepath, cam, hdus, dates):
    filepath = os.path.abspath(filepath)

    configfile = os.path.abspath(os.path.join(filepath, "last-exposure.txt"))
    curNum = get_last_exposure(configfile)

    jd = time_to_jd(dates)
    jd_to_folder(filepath, jd)

    paths = []
    for i in range(num):
        curNum += 1
        filename = (
            f"{jd[i]}/{cam.name}-{curNum:08d}.fits" if not testshot else "test.fits"
        )
        paths.append(os.path.join(filepath, filename))

        # correct fits data/header
        _hdusheader = hdus[i].header
        _hdusdata = hdus[i].data[0]
        primary_hdu = fits.PrimaryHDU(data=_hdusdata, header=_hdusheader)
        hdus[i] = fits.HDUList(
            [
                primary_hdu,
            ]
        )

    return configfile, curNum, paths


@modules.atimeit
async def write_file(
    testshot,
    num,
    hdus,
    configfile,
    curNum,
    paths,
    compress,
):
    for i in range(num):

        if not testshot:

            writeto_partial = functools.partial(
                hdus[i].writeto, paths[i], checksum=True
            )
        else:

            writeto_partial = functools.partial(
                hdus[i].writeto, paths[i], checksum=True, overwrite=True
            )
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, writeto_partial)
        set_last_exposure(configfile, curNum)
        compress_fits(paths, compress, i)


@modules.timeit
def compress_fits(paths, compress, i):
    fpack = os.path.abspath("./python/lvmcam/fpack/fpack")
    target = os.path.dirname(paths[i])
    if compress == "r":
        option = "-r"
        os.system(f"cd {target} && {fpack} {option} {paths[i]}")
        paths[i] = (paths[i], paths[i] + ".fz")
    elif compress == "h":
        option = "-h"
        os.system(f"cd {target} && {fpack} {option} {paths[i]}")
        paths[i] = (paths[i], paths[i] + ".fz")
    elif compress == "rF":
        option = "-r -F"
        os.system(f"cd {target} && {fpack} {option} {paths[i]}")
    elif compress == "rD":
        option = "-r -D"
        os.system(f"cd {target} && {fpack} {option} {paths[i]}")
        paths[i] = paths[i] + ".fz"
    elif compress == "hF":
        option = "-h -F"
        os.system(f"cd {target} && {fpack} {option} {paths[i]}")
    elif compress == "hD":
        option = "-h -D"
        os.system(f"cd {target} && {fpack} {option} {paths[i]}")
        paths[i] = paths[i] + ".fz"


@modules.timeit
def make_header_info(num, targ, kmirr, camname, exps, hdrs, status, flen):
    wcshdr = blc.get_wcshdr(connection.cs_list[0], camname, targ, kmirr, flen)
    hdus = []
    dates = []
    for i in range(num):
        hdu = exps[i].to_hdu()[0]
        dates.append(hdu.header["DATE-OBS"])
        for item in hdrs[i]:
            hdr = item[0]
            val = item[1]
            com = item[2]
            hdu.header[hdr] = (val, com)
        for item in list(status[i].items()):
            hdr = item[0]
            val = item[1]
            if len(val) > 70:
                # print(val)
                continue
            _hdr = ""
            if "Voltage" in hdr:
                _hdr = "VOLTAGE"
            elif "Current" in hdr:
                _hdr = "CURRENT"
            elif "Hz" in val:
                _hdr = "FRAME"
            else:
                _hdr = hdr.replace(" ", "")
                _hdr = _hdr.replace(".", "")
                _hdr = _hdr.upper()[:8]
            hdu.header[_hdr] = (val, hdr)
        if wcshdr is not None:
            for wcs in wcshdr:
                headerName = wcs
                headerValue = wcshdr[wcs]
                headerComment = wcshdr.comments[wcs]
                hdu.header[headerName] = (headerValue, headerComment)

        hdus.append(hdu)
    return hdus, dates


@modules.atimeit
async def expose_cam(exptime, num, cam, camname):
    exps = []
    hdrs = []
    status = []
    camera, device = connection.dev_list[camname]
    for i in range(num):
        exps.append(await cam.expose(exptime=exptime, image_type="object"))
        # camera, device = flir.setup_camera(verbose)
        status.append(await flir.vol_cur_tem(camera, device))
        hdrs.append(cam.header)
    return exps, hdrs, status, camera


@modules.atimeit
async def expose_test_cam(testshot, exptime, num, filepath, cam):
    dates = []
    for i in range(num):
        # dates.append(datetime.datetime.utcnow().isoformat())
        dates.append(datetime.datetime.utcnow())

    filepath = os.path.abspath(filepath)
    # configfile = os.path.abspath(os.path.join(filepath, "last-exposure.txt"))
    # curNum = get_last_exposure(configfile)
    # print(dates)
    # print(datetime.date.strftime(dates[0], "%Y%m%d"))
    dates2 = []
    for date in dates:
        # date_obj = datetime.datetime.strptime(date, "%Y-%m-%dT%H:%M:%S")
        date = datetime.datetime.strftime(date, '%Y%m%d')
        dates2.append(date)
    # jd = time_to_jd(dates)
    # jd_to_folder(filepath, jd)

    basename = '{camera.name}-{num:08d}.fits'
    # dirname = f'{os.path.abspath(filepath)}/{jd[0]}'
    # dirname = f'{filepath}/{jd[0]}'

    # basename = '{camera.name}-{num:04d}.fits'
    # dirname = '/data/lvm/sci/ag/{date.mjd}'

    jd_to_folder(filepath, dates2)
    paths = []
    for i in range(num):
        # curNum += 1
        # filename = (
        #     f"{jd[i]}/{cam.name}-{curNum:08d}.fits" if not testshot else "test.fits"
        # )
        # paths.append(os.path.join(filepath, filename))

        # img_path = os.path.join(filepath, filename)
        # print(type(img_path))
        original = os.path.abspath("python/lvmcam/actor/example")

        dirname = f'{filepath}/{dates2[i]}'
        image_namer = base_exp.ImageNamer(basename=basename, dirname=dirname)
        img_path = image_namer(cam)
        # print(str(img_path))
        # print(img_path)
        paths.append(str(img_path))
        if not testshot:
            await asyncio.sleep(exptime)
            shutil.copyfile(original, paths[i])

        else:
            if os.path.exists(paths[i]):
                os.remove(paths[i])
            await asyncio.sleep(exptime)
            shutil.copyfile(original, paths[i])

        # set_last_exposure(configfile, curNum)
    return filepath, paths
