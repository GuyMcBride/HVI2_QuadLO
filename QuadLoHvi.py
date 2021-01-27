# -*- coding: utf-8 -*-
"""
Created on Tue Nov 24 08:29:02 2020

@author: Guy McBride
"""

import sys
import os
import logging

log = logging.getLogger(__name__)

sys.path.append(
    "C:/Program Files/Keysight/PathWave Test Sync Executive 2020/api/python"
)
import keysight_hvi as kthvi

_hvi = None


def configure(config):
    global _hvi
    hviSystem = _defineSystem(config)
    sequencer = _defineSequences(config, hviSystem)
    log.info("Compiling HVI...")
    _hvi = sequencer.compile()
    log.info("Loading HVI to HW...")
    _hvi.load_to_hw()
    log.info("Starting HVI...")
    _hvi.run(_hvi.no_timeout)


def close():
    log.info("Releasing HVI...")
    _hvi.release_hw()


def _declareHviRegisters(config, sequencer):
    # TODO: Fix this when HVI iteration issue fixed
    log.info("Declaring HVI registers...")
    engines = sequencer.sync_sequence.engines
    scopes = sequencer.sync_sequence.scopes
    for ii in range(len(scopes)):
        for register in config.hvi.registers:
            log.info(
                "Adding register: {}, initial value: {} to module: {}".format(
                    register.name, register.value, engines[ii].name
                )
            )
            registers = scopes[ii].registers
            hviRegister = registers.add(register.name, kthvi.RegisterSize.SHORT)
            hviRegister.initial_value = register.value


def _defineSystem(config):
    sys_def = kthvi.SystemDefinition("QuadLoSystemDefinition")

    # Add Chassis resources to HVI System Definition
    sys_def.chassis.add_auto_detect()

    # Add PXI trigger resources that we plan to use
    pxiTriggers = []
    for trigger in config.hvi.triggers:
        pxiTriggerName = "PXI_TRIGGER{}".format(trigger)
        pxiTrigger = getattr(kthvi.TriggerResourceId, pxiTriggerName)
        pxiTriggers.append(pxiTrigger)
    sys_def.sync_resources = pxiTriggers

    log.info("Adding modules to the HVI environment...")
    for module in config.modules:
        engine_name = "{}_{}".format(module.model, module.slot)
        sys_def.engines.add(module.handle.hvi.engines.main_engine, engine_name)

        # Register the AWG and DAQ trigger actions and create 'general' names
        # for these to help when they are actually used in instructions
        log.info("Declaring actions used by: {}...".format(engine_name))
        if module.model == "M3202A":
            triggerRoot = "awg"
        elif module.model == "M3102A":
            triggerRoot = "daq"
        channels = int(module.handle.getOptions("channels")[-1])
        for channel in range(1, channels + 1):
            actionName = "trigger{}".format(channel)
            triggerName = "{}{}_trigger".format(triggerRoot, channel)
            actionId = getattr(module.handle.hvi.actions, triggerName)
            sys_def.engines[engine_name].actions.add(actionId, actionName)

        # Register the FPGA resources used by HVI (exposes the registers)
        if module.model == "M3202A":
            sys_def.engines[engine_name].fpga_sandboxes[0].load_from_k7z(
                os.getcwd() + "\\" + module.fpga.image_file
            )
    return sys_def


def _defineSequences(config, hviSystem):
    log.info("Creating Main Sequencer Block...")
    sequencer = kthvi.Sequencer("QuadLoSequencer", hviSystem)
    _declareHviRegisters(config, sequencer)

    # Reset the LOs and intialize any registers
    reset_block = sequencer.sync_sequence.add_sync_multi_sequence_block(
        "InitializeBlock", 30
    )
    # TODO: Fix this when HVI iteration issue fixed
    log.info("Creating Sequences for Initialization Block...")
    for ii in range(len(hviSystem.engines)):
        log.info("...Sequence for: {}".format(hviSystem.engines[ii].name))
        _Sequences.resetPhase(reset_block.sequences[hviSystem.engines[ii].name])

    #    # Configure Sync While Condition
    whileRegister = sequencer.sync_sequence.scopes[0].registers["NumberOfLoops"]
    log.info(
        "Creating Synchronized While loop, count = {}...".format(
            whileRegister.initial_value
        )
    )
    sync_while_condition = kthvi.Condition.register_comparison(
        whileRegister, kthvi.ComparisonOperator.GREATER_THAN, 0
    )
    sync_while = sequencer.sync_sequence.add_sync_while(
        "sync_while", 70, sync_while_condition
    )
    sync_block = sync_while.sync_sequence.add_sync_multi_sequence_block(
        "exec_block", 260
    )
    # TODO: Fix this when HVI iteration issue fixed
    log.info("Creating Sequences for Triggering Loop Block...")
    for ii in range(len(hviSystem.engines)):
        log.info("...Trigger sequence for: {}".format(hviSystem.engines[ii].name))
        _Sequences.triggerLoop(sync_block.sequences[hviSystem.engines[ii].name])
        reset_phase = False
        for constant in config.hvi.constants:
            if (constant.name == "ResetPhase") & (constant.value == 1):
                reset_phase = True
        if reset_phase:
            log.info(
                "...PhaseReset sequence for: {}".format(hviSystem.engines[ii].name)
            )
            _Sequences.resetPhase(sync_block.sequences[hviSystem.engines[ii].name])
    return sequencer


class _Sequences:
    def resetPhase(sequence):
        if "M32" in sequence.engine.name:
            ch4PhaseReset_register = None
            ch1PhaseReset_register = sequence.engine.fpga_sandboxes[0].fpga_registers[
                "HVI_CH1_PhaseReset"
            ]
            try:
                ch4PhaseReset_register = sequence.engine.fpga_sandboxes[
                    0
                ].fpga_registers["HVI_CH4_PhaseReset"]
            except RuntimeError:
                log.info("No CH4 registers detected")
            if ch4PhaseReset_register == None:
                _Statements.writeFpgaRegister(
                    sequence, "CH1 Pre Phase Reset", ch1PhaseReset_register, 0
                )
                _Statements.writeFpgaRegister(
                    sequence, "CH1 Phase Reset", ch1PhaseReset_register, 1
                )
                _Statements.writeFpgaRegister(
                    sequence, "CH1 Post Phase Reset", ch1PhaseReset_register, 0
                )
            else:
                _Statements.writeFpgaRegister(
                    sequence, "CH1 Pre Phase Reset", ch1PhaseReset_register, 0
                )
                _Statements.writeFpgaRegister(
                    sequence, "CH4 Pre Phase Reset", ch4PhaseReset_register, 0
                )
                _Statements.writeFpgaRegister(
                    sequence, "CH1 Phase Reset", ch1PhaseReset_register, 1
                )
                _Statements.writeFpgaRegister(
                    sequence, "CH4 Phase Reset", ch4PhaseReset_register, 1
                )
                _Statements.writeFpgaRegister(
                    sequence, "CH1 Post Phase Reset", ch1PhaseReset_register, 0
                )
                _Statements.writeFpgaRegister(
                    sequence, "CH4 Post Phase Reset", ch4PhaseReset_register, 0
                )
            loopDelay = sequence.scope.registers["Gap"].initial_value
            sequence.add_delay("Counter Settle Time", loopDelay)
            return

    def triggerLoop(sequence):
        _Statements.triggerAll(sequence, "Trigger All Channels")
        if "M32" in sequence.engine.name:
            _Statements.decrementRegister(
                sequence,
                "Decrement Loop Counter",
                sequence.scope.registers["NumberOfLoops"],
            )
            loopDelay = sequence.scope.registers["Gap"].initial_value
            sequence.add_delay("Gap Time", loopDelay)


class _Statements:
    def whileLoop(sequence, name, loopCounter):
        log.info("......While...")
        condition = kthvi.Condition.register_comparison(
            loopCounter, kthvi.ComparisonOperator.GREATER_THAN, 0
        )
        whileLoop = sequence.add_while(name, 70, condition)
        return whileLoop.sequence

    def triggerAll(sequence, name):
        log.info("......TriggerAll")
        actionCmd = sequence.instruction_set.action_execute
        actionParams = [
            sequence.engine.actions["trigger1"],
            sequence.engine.actions["trigger2"],
            sequence.engine.actions["trigger3"],
            sequence.engine.actions["trigger4"],
        ]
        instruction = sequence.add_instruction(name, 20, actionCmd.id)
        instruction.set_parameter(actionCmd.action.id, actionParams)

    def decrementRegister(sequence, name, counter, delay=10):
        log.info("......Decrement Register: {}".format(counter.name))
        instruction = sequence.add_instruction(
            name, delay, sequence.instruction_set.subtract.id
        )
        instruction.set_parameter(
            sequence.instruction_set.subtract.destination.id, counter
        )
        instruction.set_parameter(
            sequence.instruction_set.subtract.left_operand.id, counter
        )
        instruction.set_parameter(sequence.instruction_set.subtract.right_operand.id, 1)

    def writeFpgaRegister(sequence, name, register, value):
        log.info("......{}".format(name))
        regCmd = sequence.instruction_set.fpga_register_write
        instruction = sequence.add_instruction(name, 10, regCmd.id)
        instruction.set_parameter(regCmd.fpga_register.id, register)
        instruction.set_parameter(regCmd.value.id, value)
