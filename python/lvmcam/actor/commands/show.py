from __future__ import absolute_import, annotations, division, print_function

import asyncio
import os

import click
from click.decorators import command
from clu.command import Command

from lvmcam.actor import modules
from lvmcam.actor.commands import parser
from lvmcam.actor.commands.connection import cam_list
from lvmcam.araviscam import BlackflyCam as blc
from lvmcam.araviscam.aravis import Aravis


__all__ = ["show"]


@parser.group()
def show(*args):
    """
    all / connection
    """
    pass


@show.command()
@click.option("-c", "--config", type=str, default="python/lvmcam/etc/cameras.yaml")
@click.option("-v", "--verbose", is_flag=True)
async def all(command: Command, config: str, verbose: bool):
    """
    Show all cameras in configuration file.

    Parameter
    ----------
    config
        Name of the YAML file with the cameras configuration
    verbose
        Verbosity on or off
    """
    modules.change_dir_for_normal_actor_start(__file__)

    if verbose:
        modules.logger.sh.setLevel(int(verbose))
    else:
        modules.logger.sh.setLevel(modules.logging.WARNING)

    cs, available_cameras_uid = find_all_available_cameras_for_show(config)

    cameras_dict = {}
    for item in list(cs._config.items()):
        uid = item[1]["uid"]
        if uid in available_cameras_uid:
            cameras_dict[item[0]] = f"Available | uid: {uid}"
        else:
            cameras_dict[item[0]] = f"Unavailable | uid: {uid}"
    command.info(ALL=cameras_dict)
    return command.finish()


@modules.timeit
def find_all_available_cameras_for_show(config):
    cs = blc.BlackflyCameraSystem(blc.BlackflyCamera, camera_config=config)
    available_cameras_uid = cs.list_available_cameras()
    return cs, available_cameras_uid


@show.command()
# @click.option("-c", "--config", type=str, default="python/lvmcam/etc/cameras.yaml")
async def connection(
    command: Command,
    # config: str,
):
    """
    Show all connected cameras.
    """
    modules.change_dir_for_normal_actor_start(__file__)
    # cs = blc.BlackflyCameraSystem(blc.BlackflyCamera, camera_config=config)
    if cam_list:
        for cam in cam_list:
            command.info(CONNECTED={"name": cam.name, "uid": cam.uid})
        return command.finish()
    else:
        return command.error("There are no connected cameras")