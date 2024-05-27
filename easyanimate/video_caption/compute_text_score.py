import argparse
import os
from pathlib import Path

import easyocr
import numpy as np
import pandas as pd
from accelerate import PartialState
from accelerate.utils import gather_object
from natsort import natsorted
from tqdm import tqdm

from utils.logger import logger
from utils.video_utils import extract_frames, get_video_path_list


# @contextmanager
# def video_reader(*args, **kwargs):
#     vr = VideoReader(*args, **kwargs)
#     try:
#         yield vr
#     finally:
#         del vr
#         gc.collect()

# def extract_mid_frame(video_path: str):
#     with video_reader(video_path, num_threads=2) as vr:
#         middle_frame_index = len(vr) // 2
#         middle_frame = vr[middle_frame_index].asnumpy()

#         return [middle_frame_index], [middle_frame]


def triangle_area(p1, p2, p3):
    """Compute the triangle area according to its coordinates.
    """
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    tri_area = 0.5 * np.abs(x1 * y2 + x2 * y3 + x3 * y1 - x2 * y1 - x3 * y2 - x1 * y3)
    return tri_area


def compute_text_score(video_path, ocr_reader):
    _, images = extract_frames(video_path, sample_method="mid")

    frame_ocr_area_ratios = []
    for image in images:
        # horizontal detected results and free-form detected
        horizontal_list, free_list = ocr_reader.detect(np.asarray(image))
        width, height = image.shape[0], image.shape[1]

        total_area = width * height
        # rectangles
        rect_area = 0
        for xmin, xmax, ymin, ymax in horizontal_list[0]:
            if xmax < xmin or ymax < ymin:
                continue
            rect_area += (xmax - xmin) * (ymax - ymin)
        # free-form
        quad_area = 0
        try:
            for points in free_list[0]:
                triangle1 = points[:3]
                quad_area += triangle_area(*triangle1)
                triangle2 = points[3:] + [points[0]]
                quad_area += triangle_area(*triangle2)
        except:
            quad_area = 0
        text_area = rect_area + quad_area

        frame_ocr_area_ratios.append(text_area / total_area)

    video_meta_info = {
        "video_path": Path(video_path).name,
        "text_score": round(np.mean(frame_ocr_area_ratios), 5),
    }

    return video_meta_info


def parse_args():
    parser = argparse.ArgumentParser(description="Compute the text score of the middle frame in the videos.")
    parser.add_argument("--video_folder", type=str, default="", help="The video folder.")
    parser.add_argument(
        "--video_metadata_path", type=str, default=None, help="The path to the video dataset metadata (csv/jsonl)."
    )
    parser.add_argument(
        "--video_path_column",
        type=str,
        default="video_path",
        help="The column contains the video path (an absolute path or a relative path w.r.t the video_folder).",
    )
    parser.add_argument("--saved_path", type=str, required=True, help="The save path to the output results (csv/jsonl).")
    parser.add_argument("--saved_freq", type=int, default=100, help="The frequency to save the output results.")

    args = parser.parse_args()
    return args


def main():
    args = parse_args()

    video_path_list = get_video_path_list(
        video_folder=args.video_folder,
        video_metadata_path=args.video_metadata_path,
        video_path_column=args.video_path_column
    )

    if not (args.saved_path.endswith(".csv") or args.saved_path.endswith(".jsonl")):
        raise ValueError("The saved_path must end with .csv or .jsonl.")

    if os.path.exists(args.saved_path):
        if args.saved_path.endswith(".csv"):
            saved_metadata_df = pd.read_csv(args.saved_path)
        elif args.saved_path.endswith(".jsonl"):
            saved_metadata_df = pd.read_json(args.saved_path, lines=True)
        saved_video_path_list = saved_metadata_df[args.video_path_column].tolist()
        saved_video_path_list = [os.path.join(args.video_folder, video_path) for video_path in saved_video_path_list]

        video_path_list = list(set(video_path_list).difference(set(saved_video_path_list)))
        # Sorting to guarantee the same result for each process.
        video_path_list = natsorted(video_path_list)
        logger.info(f"Resume from {args.saved_path}: {len(saved_video_path_list)} processed and {len(video_path_list)} to be processed.")

    state = PartialState()
    ocr_reader = easyocr.Reader(
        lang_list=["en", "ch_sim"],
        gpu=state.device,
        recognizer=False,
        verbose=False,
        model_storage_directory="/mnt/nas/huangkunzhe.hkz/code/video-caption/models/",
        # https://pai-aigc-photog.oss-cn-hangzhou.aliyuncs.com/easyanimate/video_caption/easyocr/craft_mlt_25k.pth
    )

    # The workaround can be removed after https://github.com/huggingface/accelerate/pull/2781 is released.
    index = len(video_path_list) - len(video_path_list) % state.num_processes
    logger.info(f"Drop {len(video_path_list) % state.num_processes} videos to avoid duplicates in state.split_between_processes.")
    video_path_list = video_path_list[:index]

    result_list = []
    with state.split_between_processes(video_path_list) as splitted_video_path_list:
        for i, video_path in enumerate(tqdm(splitted_video_path_list)):
            video_meta_info = compute_text_score(video_path, ocr_reader)
            result_list.append(video_meta_info)
            if i != 0 and i % args.saved_freq == 0:
                state.wait_for_everyone()
                gathered_result_list = gather_object(result_list)
                if state.is_main_process:
                    result_df = pd.DataFrame(gathered_result_list)
                    if args.saved_path.endswith(".csv"):
                        header = False if os.path.exists(args.saved_path) else True
                        result_df.to_csv(args.saved_path, header=header, index=False, mode="a")
                    elif args.saved_path.endswith(".jsonl"):
                        result_df.to_json(args.saved_path, orient="records", lines=True, mode="a")
                    logger.info(f"Save result to {args.saved_path}.")
                result_list = []

    state.wait_for_everyone()
    gathered_result_list = gather_object(result_list)
    if state.is_main_process:
        logger.info(len(gathered_result_list))
        if len(gathered_result_list) != 0:
            result_df = pd.DataFrame(gathered_result_list)
            if args.saved_path.endswith(".csv"):
                header = False if os.path.exists(args.saved_path) else True
                result_df.to_csv(args.saved_path, header=header, index=False, mode="a")
            elif args.saved_path.endswith(".jsonl"):
                result_df.to_json(args.saved_path, orient="records", lines=True, mode="a")
            logger.info(f"Save the final result to {args.saved_path}.")


if __name__ == "__main__":
    main()