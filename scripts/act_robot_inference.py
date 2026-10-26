"""Attended ACT trial; native LeRobot select_action is the default policy path."""
import argparse
import dataclasses
import json
import queue
import select
import signal
import sys
import threading
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from lerobot.policies.act.configuration_act import ACTConfig
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.policies.factory import make_pre_post_processors
from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
from audit_lerobot_official import raw_read
from check_act_live import CALIBRATION, NAMES
from teleop_cameras import CameraMonitor
from gripper_contact_hold import GripperContactHold, InitialGripperContactHold, OpeningBoostGripperContactHold, CloseAfterReleaseGripperHold, startup_raw_goals, native_gripper_goal
from act_temporal_ensemble import TimeAlignedTemporalEnsembler
from inference_timing import control_gap_status, bounded_step_time


def bounded_action(desired, previous, bounds, dt):
    """Keep targets within calibration and limit the first-trial command rate."""
    desired = np.asarray(desired, dtype=float)
    if desired.shape != (6,) or not np.isfinite(desired).all():
        raise RuntimeError('Invalid model action')
    rates = np.array([30., 30., 30., 30., 30., 60.])
    limited = np.clip(desired, bounds[:, 0], bounds[:, 1])
    return previous + np.clip(limited-previous, -rates*dt, rates*dt)


def make_batch(observation):
    positions, images = observation
    batch = {'observation.state': torch.tensor([[positions[n] for n in NAMES]], dtype=torch.float32),
             'observation.elapsed_time': torch.zeros(1, 1),
             'observation.camera_time': torch.zeros(1, 2)}
    for name, frame in images.items():
        batch[f'observation.images.{name}'] = torch.from_numpy(frame.copy()).permute(2,0,1).unsqueeze(0).float()/255
    return batch


def configure_native_act(cfg, temporal_ensemble, ensemble_coefficient):
    cfg.temporal_ensemble_coeff = ensemble_coefficient if temporal_ensemble else None
    cfg.n_action_steps = 1 if temporal_ensemble else cfg.chunk_size
    return cfg


def native_action(policy, pre, post, observation):
    with torch.inference_mode():
        return post(policy.select_action(pre(make_batch(observation)))).cpu().numpy()[0]


def main(duration, temporal_ensemble=False, ensemble_coefficient=.01,
         native_policy=True, contact_hold=False, dry_run=False, gripper_source='ensemble',hold_profile='initial'):
    torch.set_num_threads(4)
    out = Path('/workspace/outputs/inference')/f'trial-{time.time_ns()}'
    out.mkdir(parents=True)
    report = {'motor_writes': False, 'duration_limit_s': duration, 'prediction_count': 0,
              'checkpoint': '/models/checkpoints/050000/pretrained_model',
              'temporal_ensembling': temporal_ensemble, 'control_hz_requested': 30,
              'temporal_ensemble_coefficient': ensemble_coefficient if temporal_ensemble else None,
              'native_lerobot_select_action': native_policy,
              'control_stall_limit_s': None if native_policy else 1.0,
              'prediction_policy': ('LeRobot ACTPolicy.select_action, built-in ACTTemporalEnsembler when enabled.' if native_policy else
                                   ('Time-aligned exponential average of overlapping chunks; oldest rank has highest weight for positive coefficient.'
                                    if temporal_ensemble else 'Latest chunk; action index follows elapsed time since its observation.')),
              'rate_limits': None if native_policy else 'arm 30 degrees/s; gripper 60 percentage points/s',
              'gripper_contact_hold': contact_hold,
              'gripper_hold_profile': hold_profile if contact_hold else None,
              'gripper_prediction_source': ('latest_chunk_unaveraged' if contact_hold and temporal_ensemble and not native_policy and gripper_source=='latest' else 'policy_output'),
              'gripper_release_rule': (('opening >= hold goal+3 percentage points; original successful behavior'
                                        if hold_profile=='initial' else 'opening >= observed+0.5 percentage points for 0.15s, or >= observed+2 immediately; finish opening')
                                       if contact_hold else None),
              'outcome': 'preflight', 'torque_off_verified': False}
    if contact_hold and hold_profile in ('opening-boost','opening-boost-close'):
        report['gripper_opening_completion_tolerance_percent'] = OpeningBoostGripperContactHold.release_tolerance
        report['gripper_release_rule'] = ('while holding, model opening >= measured+0.5 is promoted to at least 20% before release detection (hold goal+3); '
            'after accepted release, open to max(30%, model request, measured+5 percentage points) and finish opening; '
            'existing 60 percentage points/s opening rate limit retained')
        if hold_profile == 'opening-boost-close':
            report['post_release_close'] = ('after opening completes, close at <=60 percentage points/s with contact hold; '
                'keep closed until model requests <=5% then >=20% for another pickup')
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    cfg = ACTConfig.from_pretrained(report['checkpoint'])
    cfg.device = 'cpu'
    cfg.pretrained_backbone_weights = None
    if native_policy:
        configure_native_act(cfg,temporal_ensemble,ensemble_coefficient)
    report['n_action_steps'] = cfg.n_action_steps
    policy = ACTPolicy.from_pretrained(report['checkpoint'], config=cfg).eval()
    pre, post = make_pre_post_processors(policy_cfg=cfg, pretrained_path=report['checkpoint'],
        preprocessor_overrides={'device_processor': {'device': 'cpu'}})
    robot = SO101Follower(SO101FollowerConfig(port='/dev/so101-follower',
        id=CALIBRATION.stem, calibration_dir=CALIBRATION.parent))
    cams = CameraMonitor()
    lock = threading.Lock()
    shared = {'observation': None, 'result': None, 'error': None, 'sequence': 0}
    worker = None
    enabled = False
    gripper_hold = {'initial': InitialGripperContactHold, 'revised': GripperContactHold,
                    'opening-boost': OpeningBoostGripperContactHold,
                    'opening-boost-close': CloseAfterReleaseGripperHold}[hold_profile]()
    ensembler = TimeAlignedTemporalEnsembler(ensemble_coefficient) if temporal_ensemble and not native_policy else None
    last_ensemble_anchor = None
    previews = queue.Queue(maxsize=2)
    preview_errors = []

    def write_previews():
        while True:
            item = previews.get()
            if item is None:
                return
            second, images = item
            try:
                for name, frame in images.items():
                    Image.fromarray(frame).save(out/f'{name}-{second:03d}.jpg')
            except Exception as error:
                preview_errors.append(repr(error))

    preview_worker = threading.Thread(target=write_previews, daemon=True)
    preview_worker.start()

    def infer(observation):
        with torch.inference_mode():
            chunk = post(policy.predict_action_chunk(pre(make_batch(observation)))).cpu().numpy()[0]
        if chunk.shape != (100, 6) or not np.isfinite(chunk).all():
            raise RuntimeError('Invalid predicted action chunk')
        return chunk

    def predict_worker():
        last_sequence = -1
        try:
            while not stop.wait(.001):
                with lock:
                    item, sequence = shared['observation'], shared['sequence']
                if item is None or sequence == last_sequence:
                    continue
                anchor, observation = item
                start = time.monotonic()
                chunk = infer(observation)
                with lock:
                    shared['result'] = (anchor, chunk)
                    report['prediction_count'] += 1
                    report['last_prediction_ms'] = (time.monotonic()-start)*1000
                last_sequence = sequence
        except BaseException as error:
            with lock:
                shared['error'] = repr(error)
            stop.set()

    def observe():
        positions = robot.bus.sync_read('Present_Position', num_retry=2)
        images, times = cams.snapshot()
        if max(time.monotonic()-t for t in times) > .5:
            raise RuntimeError('Camera frame older than 500 ms')
        return positions, images

    def enter_stop():
        while not stop.wait(.05):
            if select.select([sys.stdin],[],[],0)[0]:
                line = sys.stdin.readline()
                report['operator_stop'] = 'Enter' if line else 'stdin_closed'
                stop.set()
                return

    try:
        robot.bus.connect(handshake=False)
        local = json.loads(CALIBRATION.read_text())
        actual = {n: dataclasses.asdict(c) for n,c in robot.bus.read_calibration().items()}
        if actual != local:
            raise RuntimeError('Calibration mismatch; no automatic calibration is allowed')
        for n in NAMES:
            for register in ('Torque_Enable', 'Present_Position', 'Present_Voltage', 'Operating_Mode'):
                row = raw_read(robot.bus, register, local[n]['id'])
                if not row['communication_ok'] or row['motor_error_byte']:
                    raise RuntimeError(f'{n}/{register}: {row}')
                if register in ('Torque_Enable', 'Operating_Mode') and row['value_raw'] != 0:
                    raise RuntimeError(f'{n}/{register} must be zero before trial')
                if register == 'Present_Position':
                    startup_raw_goals({n:row['value_raw']},local)
        report['preflight_torque_off_verified'] = True
        cams.start()
        initial = observe()
        for n, frame in initial[1].items():
            Image.fromarray(frame).save(out/f'{n}-start.jpg')
        # Warm up and validate model output before any motor writes.
        infer(initial)
        if native_policy:
            # Validate a native single-action prediction before enabling torque,
            # then reset its queue/ensemble so warmup is not episode history.
            preview = native_action(policy,pre,post,initial)
            report['native_preview_action'] = preview.tolist()
            if preview.shape != (6,) or not np.isfinite(preview).all():
                raise RuntimeError('Invalid native preview action')
            policy.reset()
        anchor = time.monotonic()
        chunk = infer(observe())
        shared['result'] = (anchor, chunk)
        previous = np.array([initial[0][n] for n in NAMES])
        limits = []
        for n in NAMES:
            c = local[n]
            span = (c['range_max']-c['range_min'])*180/4095
            limits.append([0,100] if n == 'gripper' else [-span,span])
        bounds = np.asarray(limits)
        if native_policy:
            report['current_state'] = initial[0]
            report['native_preview_delta'] = (preview-previous).tolist()
            report['preview_within_calibrated_range'] = bool(np.all(preview[:5] >= bounds[:5,0]) and np.all(preview[:5] <= bounds[:5,1]))
            report['preview_within_start_difference'] = bool(np.max(np.abs(preview[:5]-previous[:5])) <= 20)
            if dry_run:
                report['native_live_action_times_ms'] = []
                for _ in range(4):
                    observation = observe()
                    t = time.monotonic()
                    action = native_action(policy,pre,post,observation)
                    report['native_live_action_times_ms'].append((time.monotonic()-t)*1000)
                    if action.shape != (6,) or not np.isfinite(action).all():
                        raise RuntimeError('Invalid live native prediction')
                torque = {n:robot.bus.read('Torque_Enable',n,normalize=False,num_retry=2) for n in NAMES}
                report['torque_readback'] = torque
                report['torque_off_verified'] = not any(torque.values())
                if not report['torque_off_verified']:
                    raise RuntimeError('Torque changed during read-only check')
                report['outcome'] = 'native_live_read_only_completed'
                print(json.dumps(report,indent=2),flush=True)
                return
            if np.any(preview[:5] < bounds[:5,0]) or np.any(preview[:5] > bounds[:5,1]):
                raise RuntimeError('Native preview target exceeds calibrated range; no movement started')
            if np.max(np.abs(preview[:5]-previous[:5])) > 20:
                raise RuntimeError('Native first target differs by more than 20 degrees; align starting pose before trial')
        # Seed the existing position while torque is still off, before the
        # native configure context enables it. Preserve calibration/voltage limits.
        current_raw = robot.bus.sync_read('Present_Position', normalize=False, num_retry=2)
        startup_goals = startup_raw_goals(current_raw, local)
        report['startup_raw_positions'] = current_raw
        report['startup_raw_goals'] = startup_goals
        report['motor_writes'] = True
        enabled = True  # Cleanup also applies if native configure partially fails.
        robot.bus.sync_write('Goal_Position', startup_goals, normalize=False)
        robot.configure()
        anchor = time.monotonic()
        shared['result'] = (anchor, infer(observe()))
        start = time.monotonic()
        previous_tick = start
        shared['observation'] = (start, observe())
        if native_policy:
            policy.reset()
        else:
            worker = threading.Thread(target=predict_worker, daemon=True)
            worker.start()
        report['outcome'] = 'running'
        if duration is None:
            threading.Thread(target=enter_stop,daemon=True).start()
            print('Autonomous inference active with NO TIME LIMIT. Enter or Ctrl+C stops. Cut follower power for unexpected motion.',flush=True)
        else:
            print(f'Autonomous trial active for up to {duration}s. Cut follower power for unexpected motion.', flush=True)
        next_health = next_image = next_print = start
        health_index = 0
        next_gap_warning = start
        ticks = 0
        with (out/'control.jsonl').open('w') as log:
            while not stop.is_set() and (duration is None or time.monotonic()-start < duration):
                tick = time.monotonic()
                dt = tick-previous_tick
                if not native_policy and ticks:
                    gap_status = control_gap_status(dt)
                    report['max_control_gap_ms'] = max(report.get('max_control_gap_ms',0),dt*1000)
                    if gap_status=='stop':
                        raise RuntimeError(f'Control loop stalled for {dt:.3f}s (limit 1.0s)')
                    if gap_status=='late':
                        report['brief_loop_overruns'] = report.get('brief_loop_overruns',0)+1
                        if tick >= next_gap_warning:
                            print(f'Loop delay {dt:.3f}s; target-step limits retained.',flush=True)
                            next_gap_warning = tick+10
                observation = observe()
                if native_policy:
                    predicting = temporal_ensemble or not policy._action_queue
                    predict_start = time.monotonic()
                    desired = native_action(policy,pre,post,observation)
                    latest_chunk_gripper = None  # Native select_action already applies its ensemble/queue.
                    ensemble_gripper = float(desired[5])
                    prediction_age = time.monotonic()-predict_start
                    if prediction_age > 1.5:
                        raise RuntimeError(f'Native action selection exceeded 1.5s ({prediction_age:.3f}s)')
                    if predicting:
                        report['prediction_count'] += 1
                    report['last_prediction_ms'] = prediction_age*1000
                    contributors = min(report['prediction_count'],cfg.chunk_size) if temporal_ensemble else 1
                    index = None
                    # The policy target is passed through unchanged. Stops are
                    # wrappers; there is no custom interpolation or averaging.
                    target = np.array(desired,dtype=float,copy=True)
                    if target.shape != (6,) or not np.isfinite(target).all():
                        raise RuntimeError('Invalid native policy action')
                    if np.any(target[:5] < bounds[:5,0]) or np.any(target[:5] > bounds[:5,1]):
                        report['rejected_native_action'] = target.tolist()
                        raise RuntimeError('Native arm action exceeds calibrated movement range')
                    # The native Feetech bus clips RANGE_0_100 gripper values
                    # to [0,100] before converting to encoder counts. Match it
                    # here so a slightly negative model output does not bypass
                    # contact hold or cause an artificial range-check stop.
                    target[5] = native_gripper_goal(float(target[5]))
                else:
                    with lock:
                        shared['observation'] = (tick, observation)
                        shared['sequence'] += 1
                        result, error = shared['result'], shared['error']
                    if error:
                        raise RuntimeError(error)
                    prediction_age = tick-result[0]
                    if prediction_age > 1.5:
                        raise RuntimeError(f'Prediction older than 1.5s ({prediction_age:.3f}s)')
                    index = min(99, max(0, int(prediction_age*30)))
                    desired = result[1][index]
                    latest_chunk_gripper = float(desired[5])
                    contributors = 1
                    if ensembler is not None:
                        if result[0] != last_ensemble_anchor:
                            ensembler.add(result[0], result[1])
                            last_ensemble_anchor = result[0]
                        desired, contributors = ensembler.action(tick)
                    ensemble_gripper = float(desired[5])
                    if ensembler is not None and contact_hold and gripper_source=='latest':
                        # Experimental comparison only. The default preserves
                        # the same ensemble timing for arm and gripper targets.
                        desired = desired.copy()
                        desired[5] = latest_chunk_gripper
                    target = bounded_action(desired, previous, bounds, bounded_step_time(dt))
                gripper_before_hold = float(target[5])
                policy_gripper = float(desired[5])
                if contact_hold:
                    target[5] = gripper_hold.update(float(target[5]), observation[0]['gripper'], tick,
                                                   opening_request=policy_gripper)
                    if hold_profile == 'opening-boost-close':
                        step = 60*bounded_step_time(dt)
                        target[5] = np.clip(target[5],previous[5]-step,previous[5]+step)
                    elif gripper_hold.release_target is not None:
                        target[5] = min(target[5],previous[5]+60*bounded_step_time(dt))
                robot.send_action({f'{n}.pos':float(target[i]) for i,n in enumerate(NAMES)})
                previous = target
                log.write(json.dumps({'elapsed':tick-start,'observed':observation[0],
                                      'sent':target.tolist(),'prediction_age_s':prediction_age,
                                      'action_index':index,'ensemble_contributors':contributors,
                                      'gripper_contact_hold':gripper_hold.hold,
                                      'latest_chunk_gripper':latest_chunk_gripper,
                                      'ensemble_gripper':ensemble_gripper,
                                      'policy_gripper':policy_gripper,
                                      'gripper_before_contact_hold':gripper_before_hold,
                                      'gripper_sent':float(target[5]),
                                      'gripper_observed':observation[0]['gripper'],
                                      'gripper_hold_event':gripper_hold.last_event,
                                      'gripper_opening_pending_since':gripper_hold.opening_since,
                                      'gripper_release_target':gripper_hold.release_target,
                                      'gripper_post_release_phase':getattr(gripper_hold,'post_release_phase',None)})+'\n')
                report['max_ensemble_contributors'] = max(report.get('max_ensemble_contributors',0),contributors)
                if tick >= next_health:
                    # Spread individual status reads across the second rather
                    # than adding six serial round trips to a single tick.
                    n = NAMES[health_index]
                    row = raw_read(robot.bus, 'Present_Voltage', local[n]['id'])
                    if not row['communication_ok'] or row['motor_error_byte']:
                        raise RuntimeError(f'{n}: voltage/status fault {row}')
                    health_index = (health_index+1) % len(NAMES)
                    next_health = tick+1/len(NAMES)
                if tick >= next_image:
                    try:
                        previews.put_nowait((int(tick-start), observation[1]))
                    except queue.Full:
                        report['skipped_preview_pairs'] = report.get('skipped_preview_pairs',0)+1
                    next_image = tick+1
                if tick >= next_print:
                    print(f'{tick-start:.1f}s; predictions={report["prediction_count"]}; age={prediction_age:.2f}s; ensemble={contributors}; gripper={observation[0]["gripper"]:.1f}%', flush=True)
                    next_print = tick+2
                previous_tick = tick
                ticks += 1
                report['max_loop_work_ms'] = max(report.get('max_loop_work_ms',0),
                                                  (time.monotonic()-tick)*1000)
                stop.wait(max(0, 1/30-(time.monotonic()-tick)))
        elapsed = time.monotonic()-start
        report.update(outcome='trial_completed',control_ticks=ticks,elapsed_s=elapsed,
                      achieved_control_hz=ticks/elapsed)
    except BaseException as error:
        report.update(outcome='stopped_on_error',error=repr(error))
        raise
    finally:
        stop.set()
        report['gripper_contact_events'] = gripper_hold.contact_count
        report['gripper_release_events'] = gripper_hold.release_count
        if enabled:
            try:
                failures = []
                for n in NAMES:
                    try:
                        robot.bus.disable_torque(n, num_retry=2)
                    except BaseException as error:
                        failures.append(f'{n}: {error}')
                torque = {}
                for n in NAMES:
                    try:
                        torque[n] = robot.bus.read('Torque_Enable',n,normalize=False,num_retry=2)
                    except BaseException as error:
                        failures.append(f'{n} verification: {error}')
                report['torque_readback'] = torque
                report['torque_disable_errors'] = failures
                if failures:
                    raise RuntimeError('; '.join(failures))
                report['torque_off_verified'] = not any(torque.values())
                if not report['torque_off_verified']:
                    raise RuntimeError(f'Torque remains enabled: {torque}')
                print('Follower torque OFF verified.',flush=True)
            except BaseException as error:
                report['cleanup_error'] = repr(error)
                print(f'POWER OFF FOLLOWER: torque-off verification failed: {error}',flush=True)
        if worker:
            worker.join(timeout=3)
        while True:
            try:
                previews.put_nowait(None)
                break
            except queue.Full:
                previews.get_nowait()
        preview_worker.join(timeout=2)
        report['preview_errors'] = preview_errors
        cams.close()
        robot.bus.port_handler.closePort()
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(f'Inference report: {out}/report.json',flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration',type=float,default=30)
    parser.add_argument('--until-enter',action='store_true',help='No fixed duration; Enter or Ctrl+C stops')
    parser.add_argument('--temporal-ensemble',action='store_true')
    parser.add_argument('--ensemble-coefficient',type=float,default=.01)
    parser.add_argument('--legacy-async',action='store_true',help='Use the previous custom asynchronous scheduler')
    parser.add_argument('--contact-hold',action='store_true',help='Opt in to custom gripper contact hold; disabled in native mode by default')
    parser.add_argument('--dry-run',action='store_true',help='Read live observations and predict with native policy; no motor writes')
    parser.add_argument('--gripper-source',choices=('ensemble','latest'),default='ensemble',
                        help='Keep arm/gripper targets coordinated; latest is an experimental asynchronous override')
    parser.add_argument('--gripper-hold-profile',choices=('initial','revised','opening-boost','opening-boost-close'),default='initial',
                        help='initial restores the original confirmed-success contact/release logic')
    args = parser.parse_args()
    if not args.until_enter and not 0 < args.duration <= 60:
        parser.error('First-trial duration must be between 0 and 60 seconds')
    if not np.isfinite(args.ensemble_coefficient):
        parser.error('Ensemble coefficient must be finite')
    if args.dry_run and args.legacy_async:
        parser.error('--dry-run checks the native policy path; omit --legacy-async')
    if args.gripper_source=='latest' and not (args.legacy_async and args.temporal_ensemble and args.contact_hold):
        parser.error('--gripper-source=latest requires --legacy-async --temporal-ensemble --contact-hold')
    main(None if args.until_enter else args.duration,args.temporal_ensemble,args.ensemble_coefficient,
         native_policy=not args.legacy_async,contact_hold=args.contact_hold,dry_run=args.dry_run,
         gripper_source=args.gripper_source,hold_profile=args.gripper_hold_profile)
