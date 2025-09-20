#!/usr/bin/env python3

from common.controller_helper import create_experimental_model_forwards, ControllerExceptionHandling

with ControllerExceptionHandling():
    create_experimental_model_forwards()