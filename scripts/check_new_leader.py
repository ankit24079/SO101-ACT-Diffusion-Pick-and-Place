"""Read-only manual SO-101 check, selectable arm; no calibration/motor writes."""
import dataclasses
import argparse
import importlib.metadata
import json
import select
import signal
import sys
import time
from pathlib import Path

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus

NAMES = ('shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper')
JOINT_CHECKS = (
    ('shoulder_pan', 'Rotate the BOTTOM BASE gently left/right; do not lift the arm.'),
    ('shoulder_lift', 'Raise/lower the FIRST HINGE ABOVE THE BASE; keep the rotating base still.'),
    ('elbow_flex', 'Bend/straighten the MIDDLE ELBOW hinge while supporting the arm.'),
    ('wrist_flex', 'Bend the WRIST HINGE just behind the gripper up/down.'),
    ('wrist_roll', 'Rotate the GRIPPER about its length axis only as far as cables comfortably permit; never wind or stretch wires.'),
    ('gripper', 'Open/close the GRIPPER JAWS gently; keep fingers outside the jaws.'),
)


class ReadOnlyBus(FeetechMotorsBus):
    def write(self,*args,**kwargs):
        raise RuntimeError('Motor writes forbidden in manual inspection')
    def _write(self,*args,**kwargs):
        raise RuntimeError('Motor writes forbidden in manual inspection')
    def sync_write(self,*args,**kwargs):
        raise RuntimeError('Motor writes forbidden in manual inspection')


def read(bus,register,name):
    try:
        return bus.read(register,name,normalize=False)
    except Exception as error:
        raise RuntimeError(f'{bus.port}/{name}/{register}: {error}') from error


def sample(bus,limits,row=None):
    if row is None:
        row={}
    row.update(monotonic_seconds=time.monotonic(),torque_enable={},positions_raw={},voltages_raw={})
    try:
        for name in NAMES:
            row['torque_enable'][name]=read(bus,'Torque_Enable',name)
        if any(row['torque_enable'].values()):
            raise RuntimeError(f'STOP manual handling: arm torque not OFF: {row["torque_enable"]}')
        # Save voltage first so a subsequent position fault retains the nearest
        # successful supply readings. Sequential samples can still miss spikes.
        for name in NAMES:
            value=read(bus,'Present_Voltage',name)
            row['voltages_raw'][name]=value
            if not limits[name]['min'] <= value <= limits[name]['max']:
                raise RuntimeError(f'{name}: voltage register {value} outside configured limits')
        for name in NAMES:
            row['positions_raw'][name]=read(bus,'Present_Position',name)
    except Exception as error:
        row['error']=str(error)
        raise
    return row


def summarize(report):
    rows=[report.get('initial',{})]+[row for rows in report['stages'].values() for row in rows]+[report.get('final',{})]
    summary={}
    for name in NAMES:
        positions=[r['positions_raw'][name] for r in rows if name in r.get('positions_raw',{})]
        volts=[r['voltages_raw'][name] for r in rows if name in r.get('voltages_raw',{})]
        cal=report.get('stored_calibration',{}).get(name)
        summary[name]={
            'position_min_max':[min(positions),max(positions)] if positions else None,
            'voltage_min_max_raw':[min(volts),max(volts)] if volts else None,
            'stored_range':[cal['range_min'],cal['range_max']] if cal else None,
            'outside_stored_range_count':sum(not cal['range_min']<=v<=cal['range_max'] for v in positions) if cal else None,
            'large_encoder_jumps':sum(abs(b-a)>2048 for a,b in zip(positions,positions[1:])),
        }
    return summary


def interrupted(signum,frame):
    raise KeyboardInterrupt


def main(joint=None,all_joints=False,role='leader'):
    if importlib.metadata.version('lerobot')!='0.6.1':
        raise RuntimeError('Review this inspection for the installed LeRobot version')
    bus=ReadOnlyBus(f'/dev/so101-{role}',{name:Motor(i,'sts3215',MotorNormMode.RANGE_0_100) for i,name in enumerate(NAMES,1)})
    report={'status':'started','powered':False,'role':role,'selected_joint':'all' if all_joints else joint,'stages':{},'note':'Manual read-only travel check, not a new calibration or proof of safe limits.'}
    directory=Path('/workspace/outputs')/('new-leader-check' if role=='leader' else 'repaired-follower-check')
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/(str(time.time_ns())+'.json')
    try:
        bus.connect(handshake=False)
        for name in NAMES:
            if bus.ping(name,raise_on_error=True)!=bus.model_number_table['sts3215']:
                raise RuntimeError(f'{name}: unexpected motor model')
            if read(bus,'Torque_Enable',name)!=0:
                raise RuntimeError(f'{name}: torque must already be OFF; no settings changed')
        report['stored_calibration']={name:dataclasses.asdict(c) for name,c in bus.read_calibration().items()}
        report['phase_raw']={name:read(bus,'Phase',name) for name in NAMES}
        limits={name:{'min':read(bus,'Min_Voltage_Limit',name),'max':read(bus,'Max_Voltage_Limit',name)} for name in NAMES}
        report['voltage_limits_raw']=limits
        report['initial']={}
        sample(bus,limits,report['initial'])
        print(f'{role}: all six motors report torque OFF. Only this arm is mapped.',flush=True)
        print(f'Support the {role}, clear its reach, keep fingers outside jaws/pinch points, and never force resistance.',flush=True)
        checks = (
            ('elbow','Gently bend ONLY the leader elbow through a comfortable range, then return it. Do not force mechanical stops.'),
            ('gripper','Gently open and close ONLY the leader gripper through its comfortable travel. Keep fingers outside the jaws.'),
        )
        if joint == 'shoulder_lift':
            checks = (('shoulder_lift', f'With the {role} supported, move ONLY the FIRST HINGE ABOVE THE ROTATING BASE slightly away from the folded resting pose and back. Use a small movement; do not sweep the full range or force resistance.'),)
        if all_joints:
            checks = JOINT_CHECKS
        for name,instruction in checks:
            input(f'Press ENTER when supported and clear to start the {name} check: ')
            print(instruction,flush=True)
            print('Sampling now. Press ENTER after completing that movement; no time limit.',flush=True)
            rows=report['stages'][name]=[]
            last_print=-1
            while True:
                if select.select([sys.stdin],[],[],0)[0]:
                    sys.stdin.readline()
                    break
                row={};rows.append(row)
                sample(bus,limits,row)
                if row['monotonic_seconds']-last_print>=.5:
                    print(json.dumps({'positions_raw':row['positions_raw'],'voltage_raw':row['voltages_raw']}),flush=True)
                    last_print=row['monotonic_seconds']
                time.sleep(.15)
        report['final']={}
        sample(bus,limits,report['final'])
        report['status']='complete'
    except BaseException as error:
        report['status']='interrupted' if isinstance(error,KeyboardInterrupt) else 'error'
        report['error']=str(error)
        raise
    finally:
        bus.port_handler.closePort()
        report['range_summary']=summarize(report)
        path.write_text(json.dumps(report,indent=2)+'\n')
        print(f'{role} inspection saved: {path}. No motor settings or local calibration changed.',flush=True)


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--role', choices=('leader','follower'), default='leader')
    parser.add_argument('--joint', choices=('shoulder_lift',), default=None)
    parser.add_argument('--all-joints', action='store_true', help='Check all six selected-arm joints manually, one at a time, with torque off')
    args = parser.parse_args()
    if args.all_joints and args.joint:
        parser.error('Choose --all-joints or --joint')
    signal.signal(signal.SIGTERM,interrupted)
    main(args.joint,args.all_joints,args.role)
