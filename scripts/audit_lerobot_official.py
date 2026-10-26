"""Read-only installed-source and motor-register audit. No configure/torque writes.

Direct SDK READ responses preserve raw motor error bits even on faulting replies.
This is diagnostic only: a flagged reply is never treated as approval to move.
"""
import argparse
import hashlib
import importlib.metadata as metadata
import importlib.util
import json
import time
from pathlib import Path

LEROBOT_FILES = (
    'scripts/lerobot_teleoperate.py', 'robots/so_follower/so_follower.py',
    'robots/so_follower/config_so_follower.py', 'teleoperators/so_leader/so_leader.py',
    'teleoperators/so_leader/config_so_leader.py', 'motors/feetech/feetech.py',
    'motors/feetech/tables.py', 'motors/motors_bus.py',
)
SDK_FILES = ('group_sync_read.py','group_sync_write.py','protocol_packet_handler.py','port_handler.py','scservo_def.py')
NAMES = ('shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper')
REGISTERS = (
    'Torque_Enable','Lock','Operating_Mode','Phase','Return_Delay_Time',
    'P_Coefficient','I_Coefficient','D_Coefficient','Maximum_Acceleration','Acceleration',
    'Max_Torque_Limit','Torque_Limit','Protection_Current','Overload_Torque',
    'Protection_Time','Over_Current_Protection_Time','Min_Voltage_Limit','Max_Voltage_Limit',
    'Min_Position_Limit','Max_Position_Limit','Homing_Offset','Present_Voltage',
    'Present_Position','Present_Temperature','Present_Current','Present_Load','Status',
)
FLAGS = {1:'input_voltage',2:'angle_sensor',4:'overheat',8:'overcurrent',32:'overload'}


def raw_read(bus, name, motor_id):
    table = bus.model_ctrl_table['sts3215']
    if name not in table:
        return {'supported':False}
    address,length=table[name]
    fn={1:bus.packet_handler.read1ByteTxRx,2:bus.packet_handler.read2ByteTxRx,4:bus.packet_handler.read4ByteTxRx}[length]
    value,comm,error=fn(bus.port_handler,motor_id,address)
    return {'supported':True,'address':address,'bytes':length,'value_raw':int(value),
            'comm_result':int(comm),'communication_ok':comm==bus._comm_success,
            'motor_error_byte':int(error),'motor_error_flags':[text for bit,text in FLAGS.items() if error & bit],
            'unclassified_error_bits':int(error & ~sum(FLAGS)),
            'sdk_error_text':bus.packet_handler.getRxPacketError(error) if error else '',
            'note':'Fault flags are recorded, not ignored; raw value alone does not clear a fault.'}


def copy_sources(report,out):
    for package,names in (('lerobot',LEROBOT_FILES),('scservo_sdk',SDK_FILES)):
        spec=importlib.util.find_spec(package)
        root=Path(next(iter(spec.submodule_search_locations)))
        hashes={}
        for relative in names:
            source=root/relative
            if source.is_file():
                data=source.read_bytes();dest=out/'installed'/package/relative
                dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
                hashes[relative]=hashlib.sha256(data).hexdigest()
        report['source_sha256'][package]=hashes


def main(inspect_motors):
    out=Path('/workspace/outputs/official-audit')/str(time.time_ns())
    out.mkdir(parents=True,exist_ok=False)
    report={'status':'started','motor_writes':False,'versions':{},'source_sha256':{},'arms':{}}
    try:
        for name in ('lerobot','feetech-servo-sdk','pyserial','torch'):
            report['versions'][name]=metadata.version(name)
        copy_sources(report,out)
        from lerobot.robots.so_follower import SO101FollowerConfig
        from lerobot.teleoperators.so_leader import SO101LeaderConfig
        follower=SO101FollowerConfig(port='not-opened')
        leader=SO101LeaderConfig(port='not-opened')
        report['installed_config_defaults']={
            'follower':{key:getattr(follower,key) for key in ('position_p_coefficient','position_i_coefficient','position_d_coefficient','num_read_retries','use_degrees','max_relative_target')},
            'leader':{key:getattr(leader,key) for key in ('num_read_retries','use_degrees')},
        }
        if inspect_motors:
            if report['versions']['lerobot']!='0.6.1' or report['versions']['feetech-servo-sdk']!='1.0.0':
                raise RuntimeError('Installed versions differ; source export saved, review before serial inspection')
            from lerobot.motors import Motor,MotorNormMode
            from lerobot.motors.feetech import FeetechMotorsBus
            for role in ('leader','follower'):
                bus=FeetechMotorsBus(f'/dev/so101-{role}',{name:Motor(i,'sts3215',MotorNormMode.RANGE_0_100) for i,name in enumerate(NAMES,1)})
                arm=report['arms'][role]={'motors':{}}
                try:
                    bus.connect(handshake=False)
                    for name,motor in bus.motors.items():
                        motor_report=arm['motors'][name]={'id':motor.id,'registers':{}}
                        model=raw_read(bus,'Model_Number',motor.id);motor_report['model']=model
                        if not model.get('communication_ok') or model['value_raw']!=bus.model_number_table['sts3215']:
                            motor_report['status']='model_or_communication_mismatch';continue
                        for register in REGISTERS:
                            motor_report['registers'][register]=raw_read(bus,register,motor.id)
                        motor_report['status']='read_complete'
                    arm['status']=('read_complete' if all(m['status']=='read_complete' for m in arm['motors'].values())
                                   else 'read_incomplete')
                finally:
                    bus.port_handler.closePort()
        report['status']=('incomplete' if any(a['status']!='read_complete' for a in report['arms'].values())
                          else 'complete')
    except BaseException as error:
        report.update(status='error',error=str(error))
        raise
    finally:
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print('Installed versions:',report['versions'],flush=True)
        print('Config defaults:',json.dumps(report.get('installed_config_defaults',{})),flush=True)
        for role,arm in report['arms'].items():
            for name,motor in arm['motors'].items():
                responses={'Model_Number':motor.get('model',{}),**motor['registers']}
                faults={reg:row for reg,row in responses.items() if row.get('motor_error_byte') or row.get('communication_ok') is False}
                if faults:print('Diagnostic faults:',role,name,json.dumps(faults),flush=True)
        if report['status']=='incomplete':
            print('INSPECTION INCOMPLETE: one or more expected motors did not respond. Calibration and torque state cannot be verified for those motors.',flush=True)
        print(f'Read-only official/runtime audit saved: {out}/report.json. No motor settings were written.',flush=True)
    return out, report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--inspect-motors',action='store_true',help='READ registers on both arms; never enables torque or writes settings')
    main(parser.parse_args().inspect_motors)
