import matplotlib

import matplotlib.pyplot as plt

from PIL import Image
import cv2
import torch
import airsim

import sys
import os
import wandb
import socket
import setproctitle
import numpy as np
from pathlib import Path
import torch
import configparser
from onpolicy.config import get_config
from onpolicy.envs.mpe.MPE_env import MPEEnv
from onpolicy.envs.env_wrappers import SubprocVecEnv, DummyVecEnv
from onpolicy.envs.airsim_envs.airsim_env import AirSimDroneEnv
from onpolicy.algorithms.r_mappo.algorithm.r_actor_critic import R_Actor, R_Critic
############################ detect begin ##########################################
#初始化目录
FILE = Path(__file__).resolve()
ROOT = FILE.parents[0]  # 定义YOLOv5的根目录
if str(ROOT) not in sys.path:
  sys.path.append(str(ROOT))  # 将YOLOv5的根目录添加到环境变量中（程序结束后删除）
ROOT = Path(os.path.relpath(ROOT, Path.cwd()))  # relative

from detect.models.common import DetectMultiBackend
from detect.utils.datasets import IMG_FORMATS, VID_FORMATS, LoadImages, LoadStreams
from detect.utils.general import (LOGGER, check_file, check_img_size, check_imshow, check_requirements, colorstr,
                         increment_path, non_max_suppression, print_args, scale_coords, strip_optimizer, xyxy2xywh)
from detect.utils.plots import Annotator, colors, save_one_box
from detect.utils.torch_utils import select_device, time_sync

#导入letterbox
from detect.utils.augmentations import Albumentations, augment_hsv, copy_paste, letterbox, mixup, random_perspective

weights=ROOT / 'yolov5s.pt'  # 权重文件地址   .pt文件
source=ROOT / 'data/images'  # 测试数据文件(图片或视频)的保存路径
data=ROOT / 'data/coco128.yaml'  # 标签文件地址   .yaml文件

imgsz=(640, 640)  # 输入图片的大小 默认640(pixels)
conf_thres=0.25  # object置信度阈值 默认0.25  用在nms中
iou_thres=0.45  # 做nms的iou阈值 默认0.45   用在nms中
max_det=1000  # 每张图片最多的目标数量  用在nms中
device='0'  # 设置代码执行的设备 cuda device, i.e. 0 or 0,1,2,3 or cpu
classes=None  # 在nms中是否是只保留某些特定的类 默认是None 就是所有类只要满足条件都可以保留 --class 0, or --class 0 2 3
agnostic_nms=False  # 进行nms是否也除去不同类别之间的框 默认False
augment=False  # 预测是否也要采用数据增强 TTA 默认False
visualize=False  # 特征图可视化 默认FALSE
half=False  # 是否使用半精度 Float16 推理 可以缩短推理时间 但是默认是False
dnn=False  # 使用OpenCV DNN进行ONNX推理

# 获取设备
device = select_device(device)

# 载入模型
model = DetectMultiBackend(weights, device=device, dnn=dnn, data=data)
stride, names, pt, jit, onnx, engine = model.stride, model.names, model.pt, model.jit, model.onnx, model.engine
imgsz = check_img_size(imgsz, s=stride)  # 检查图片尺寸

# Half
# 使用半精度 Float16 推理
half &= (pt or jit or onnx or engine) and device.type != 'cpu'  # FP16 supported on limited backends with CUDA
if pt or jit:
    model.model.half() if half else model.model.float()


def detect(img):
    # Dataloader
    # 载入数据
    dataset = LoadImages(source, img_size=imgsz, stride=stride, auto=pt)
    # Run inference
    # 开始预测
    model.warmup(imgsz=(1, 3, *imgsz))  # warmup
    dt, seen = [0.0, 0.0, 0.0], 0
    #对图片进行处理
    im0 = img
    # Padded resize
    im = letterbox(im0, imgsz, stride, auto=pt)[0]
    # Convert
    im = im.transpose((2, 0, 1))[::-1]  # HWC to CHW, BGR to RGB
    im = np.ascontiguousarray(im)
    t1 = time_sync()
    im = torch.from_numpy(im).to(device)
    im = im.half() if half else im.float()  # uint8 to fp16/32
    im /= 255  # 0 - 255 to 0.0 - 1.0
    if len(im.shape) == 3:
        im = im[None]  # expand for batch dim
    t2 = time_sync()
    dt[0] += t2 - t1
    # Inference
    # 预测
    pred = model(im, augment=augment, visualize=visualize)
    t3 = time_sync()
    dt[1] += t3 - t2
    # NMS
    pred = non_max_suppression(pred, conf_thres, iou_thres, classes, agnostic_nms, max_det=max_det)
    dt[2] += time_sync() - t3
    #用于存放结果
    detections=[]
    # Process predictions
    for i, det in enumerate(pred):  # per image 每张图片
        seen += 1
        # im0 = im0s.copy()
        gn = torch.tensor(im0.shape)[[1, 0, 1, 0]]
        imc = im0.copy()
        annotator = Annotator(im0, line_width=3, example=str(names))
        if len(det):
            # Rescale boxes from img_size to im0 size
            det[:, :4] = scale_coords(im.shape[2:], det[:, :4], im0.shape).round()
            # Write results
            # 写入结果
            for *xyxy, conf, cls in reversed(det):
                c = int(cls)
                xywh = (xyxy2xywh(torch.tensor(xyxy).view(1, 4))).view(-1).tolist()
                xywh = [round(x) for x in xywh]
                xywh = [xywh[0] - xywh[2] // 2, xywh[1] - xywh[3] // 2, xywh[2],
                      xywh[3]]  # 检测到目标位置，格式：（left，top，w，h）
                cls = names[int(cls)]
                conf = float(conf)
                detections.append({'class': cls, 'conf': conf, 'position': xywh})

                  # integer class
                label = None
                if c == 0:
                    annotator.box_label(xyxy, label, color=colors(c, True))

        im0 = annotator.result()
        cv2.imwrite('out.jpg', im0)
    for i in detections:
        print(i)

    # LOGGER.info(f'({t3 - t2:.3f}s)')
    return detections
plt.ion()
matplotlib.use('QtAgg')

################### detect init end #############################
################### run model begin #############################
default_cfg = '../onpolicy/envs/airsim_envs/cfg/default.cfg'

class Myconf(configparser.ConfigParser):
    def __init__(self, defaults=None):
        configparser.ConfigParser.__init__(self, defaults=None)

    def optionxform(self, optionstr: str) -> str:
        return optionstr


def make_train_env(cfg):
    def get_env_fn(rank):
        def init_env():
            if cfg.get('options', 'env') == "airsim":
                env = AirSimDroneEnv(cfg)
            else:
                print("Can not support the " +
                      cfg.get('options', 'env') + "environment.")
                raise NotImplementedError
            env.seed(cfg.getint('algorithm', 'seed') + rank * 1000)
            return env
        return init_env

    if cfg.getint('algorithm', 'n_rollout_threads') == 1:
        return DummyVecEnv([get_env_fn(0)])
    else:
        return SubprocVecEnv([get_env_fn(i) for i in range(cfg.getint('algorithm', 'n_rollout_threads'))])


def make_eval_env(cfg):
    def get_env_fn(rank):
        def init_env():
            if cfg.get('options', 'env') == "airsim":
                env = AirSimDroneEnv(cfg)
            else:
                print("Can not support the " +
                      cfg.get('options', 'env') + "environment.")
                raise NotImplementedError
            env.seed(cfg.getint('algorithm', 'seed')*50000 + rank * 10000)
            return env
        return init_env

    if cfg.getint('algorithm', 'n_rollout_threads') == 1:
        return DummyVecEnv([get_env_fn(0)])
    else:
        return SubprocVecEnv([get_env_fn(i) for i in range(cfg.getint('algorithm', 'n_rollout_threads'))])


def parse_args(args, parser):
    parser.add_argument('--scenario_name', type=str,
                        default='simple_spread', help="Which scenario to run on")
    parser.add_argument("--num_landmarks", type=int, default=3)
    parser.add_argument('--num_agents', type=int,
                        default=2, help="number of players")

    all_args = parser.parse_known_args(args)[0]

    return all_args


def _t2n(x):
    return x.detach().cpu().numpy()


cfg = Myconf()
cfg.read(default_cfg)
for each in cfg.items("algorithm"):
    cfg.__dict__[each[0]] = each[1]

if cfg.get('algorithm', 'algorithm_name') == "rmappo":
    assert cfg.getboolean('algorithm', 'use_recurrent_policy') or cfg.getboolean('algorithm', 'use_naive_recurrent_policy'), ("check recurrent policy!")
elif cfg.get('algorithm', 'algorithm_name')  == "mappo":
    assert cfg.getboolean('algorithm', 'use_recurrent_policy') == False and cfg.getboolean('algorithm', 'use_naive_recurrent_policy') == False, ("check recurrent policy!")
else:
    raise NotImplementedError


# cuda

if cfg.getboolean('algorithm', 'cuda') and torch.cuda.is_available():
    print("choose to use gpu...")
    device = torch.device("cuda:0")
    torch.set_num_threads(cfg.getint('algorithm', 'n_training_threads'))
    if cfg.getboolean('algorithm', 'cuda_deterministic'):
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
else:
    print("choose to use cpu...")
    device = torch.device("cpu")
    torch.set_num_threads(cfg.getint('algorithm', 'n_training_threads'))

# seed
torch.manual_seed(cfg.getint('algorithm', 'seed'))
torch.cuda.manual_seed_all(cfg.getint('algorithm', 'seed'))
np.random.seed(cfg.getint('algorithm', 'seed'))


# env init
envs = AirSimDroneEnv(cfg)
eval_envs = make_eval_env(cfg) if cfg.getboolean('algorithm', 'use_eval') else None
num_agents = cfg.getint('options', 'num_of_drone')

config = {
    "cfg": cfg,
    "envs": envs,
    "eval_envs": eval_envs,
    "num_agents": num_agents,
    "device": device
}

# load model
policy_actor_state_dict = torch.load(str(cfg.get("algorithm", 'model_dir')) + '/actor.pt')

envs.reset()
actor1 = R_Actor(config['cfg'], config['envs'].observation_space[0], config['envs'].action_space[0], config['device'])
actor1.load_state_dict(policy_actor_state_dict)

actor2 = R_Actor(config['cfg'], config['envs'].observation_space[0], config['envs'].action_space[0], config['device'])
actor2.load_state_dict(policy_actor_state_dict)

rnn_states_actor_n = []
rnn_states_actor = np.zeros(
    (1, 1, 64),
    dtype=np.float32)
masks = np.ones((1, 1), dtype=np.float32)

rnn_states_actor_n.append(rnn_states_actor)
rnn_states_actor_n.append(rnn_states_actor)

obs = []

obs.append(envs._get_obs(envs.agents[0]))
obs.append(envs._get_obs(envs.agents[1]))

obs[0] = np.reshape(obs[0],(1,444))
obs[1] = np.reshape(obs[1],(1,444))

action_n = np.array([0,0])
out = [1,1]
while True:
    # plt.clf()
    # agraphic = plt.subplot(2, 1, 1)
    # plt.subplots_adjust(left=0, bottom=0, right=1, top=1)

    # 1
    tmp, _, rnn_states_actor_n[0] = actor1(obs[0], rnn_states_actor_n[0], masks)
    action_n[0] = int(tmp[0][0])
    rnn_states_actor_n[0] = np.array(np.split(_t2n(rnn_states_actor_n[0]), 1))
    rnn_states_actor_n[0] = np.reshape(rnn_states_actor_n[0], (1,1,64))
    # action_n[0] = np.array(np.split(_t2n(action_n[0]), 1))
    # action_n[0] = np.reshape(action_n[0],(1,1))
    # 2
    tmp, _, rnn_states_actor_n[1] = actor2(obs[1], rnn_states_actor_n[1], masks)
    action_n[1] = int(tmp[0][0])
    rnn_states_actor_n[1] = np.array(np.split(_t2n(rnn_states_actor_n[1]), 1))
    rnn_states_actor_n[1] = np.reshape(rnn_states_actor_n[1], (1, 1, 64))
    # action_n[1] = np.array(np.split(_t2n(action_n[1]), 1))
    # action_n[1] = np.reshape(action_n[1], (1, 1))
    action_n = np.reshape(action_n, (2, 1))
    obs, rewards, dones, infos = envs.step(action_n)

    # detect
    # img_rgb = envs.get_raw_image(envs.agents[0],0)
    # detect(img_rgb)
    # img = Image.open('out.jpg')
    # agraphic.imshow(img)
    # plt.show()
    # plt.pause(0.01)

    obs[0] = np.reshape(obs[0], (1, 444))
    obs[1] = np.reshape(obs[1], (1, 444))
    if envs.agents[0].is_in_desired_pose():

        envs.client.enableApiControl(False,'cf101')
    if envs.agents[1].is_in_desired_pose():
        envs.client.enableApiControl(False,'cf102')




