import argparse
import json
import datetime
import re
import os
import logging
import shutil
from modules import Chronometer
from process_input import process_input

# Create and start the chronometer
chrono = Chronometer()
chrono.start()

TMP_DIR = "./tmp/"

# Set up logging
logging.basicConfig(level=logging.INFO)

def convert_to_srt_time(time_in_seconds):
    formatted_time = datetime.timedelta(seconds=time_in_seconds)
    hours, remainder = divmod(formatted_time.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    hours += formatted_time.days * 24  # add days to hours if there are any
    milliseconds = formatted_time.microseconds // 1000
    return "{:02}:{:02}:{:02},{:03}".format(hours, minutes, seconds, milliseconds)

def generate_subtitle_entry(index, start_time, end_time, text):
    """Generate a subtitle entry."""
    start_srt = convert_to_srt_time(start_time)
    end_srt = convert_to_srt_time(end_time)
    return f"{index}\n{start_srt} --> {end_srt}\n{text}\n\n"

def create_srt_content(json_files):
    segments = []
    for json_file in json_files:
        with open(f"{TMP_DIR}{json_file}", 'r', encoding='utf-8') as file:
            data = json.load(file)
            offset = extract_time_from_filename(json_file)
            if offset is not None:
                for segment in data['segments']:
                    segment['start'] += offset
                    segment['end'] += offset
            segments.extend(data['segments'])

    index = 1
    current_text = None
    start_time = None
    end_time = None
    entries = []

    for segment in segments:
        if current_text is not None and current_text != segment['text']:
            entries.append(generate_subtitle_entry(index, start_time, end_time, current_text))
            index += 1
            current_text = segment['text']
            start_time = segment['start']
            end_time = segment['end']
        else:
            if current_text is None:
                current_text = segment['text']
                start_time = segment['start']
            end_time = segment['end']

    if current_text is not None:
        entries.append(generate_subtitle_entry(index, start_time, end_time, current_text))

    return ''.join(entries)

class Subtitle:
    def __init__(self, index, start, end, text):
        self.index = index
        self.start = start
        self.end = end
        self.text = text

    @classmethod
    def from_srt_block(cls, block):
        lines = block.strip().split("\n")
        index = lines[0]
        start, end = cls.parse_time_range(lines[1])
        text = "\n".join(lines[2:]).strip()
        return cls(index, start, end, text)

    @staticmethod
    def parse_time_range(time_range):
        time_format = '%H:%M:%S,%f'
        start_str, end_str = time_range.split(" --> ")
        start = datetime.datetime.strptime(start_str.strip(), time_format).time()
        end = datetime.datetime.strptime(end_str.strip(), time_format).time()
        return start, end

    @staticmethod
    def time_to_str(time):
        return time.strftime('%H:%M:%S,%f')[:-3]  # remove last three digits (micro -> milliseconds)

    def to_srt_block(self):
        start_str = self.time_to_str(self.start)
        end_str = self.time_to_str(self.end)
        return f"{self.index}\n{start_str} --> {end_str}\n{self.text}\n"

def parse_srt(srt_content):
    blocks = srt_content.split("\n\n")
    return [Subtitle.from_srt_block(block) for block in blocks if block.strip()]

def merge_srt_content(srt1_content, srt2_content):
    subtitles1 = parse_srt(srt1_content)
    subtitles2 = parse_srt(srt2_content)

    # Logic for replacing the content from srt1 with srt2 based on the time range.
    merged_subtitles = subtitles1
    for sub2 in subtitles2:
        # Remove any overlapping subtitles from srt1
        merged_subtitles = [sub for sub in merged_subtitles if not (sub.start < sub2.end and sub2.start < sub.end)]
        # Merge the subtitles list while maintaining the order
        merged_subtitles = sorted(merged_subtitles + [sub2], key=lambda sub: sub.start)
        # Re-index the subtitles
        i = 1  # subtitle index for the new merged content
        for sub in merged_subtitles:
            sub.index = i
            i += 1

    # Convert the merged subtitles back to SRT format
    merged_srt_content = "\n\n".join(sub.to_srt_block() for sub in merged_subtitles)
    return merged_srt_content

def extract_time_from_filename(filename):
    """
    Extract the time information from the file name and convert it to seconds.

    :param filename: str, the file name which contains the time information
    :return: time_in_seconds, the float time in seconds format or None if there is a format mismatch
    """
    
    # Use regex to find the time pattern in the filename.
    match = re.search(r'(\d{6})_(\d{6})\.json$', filename)
    
    if match:
        # If a matching segment is found, isolate the required time segment (the second group in this case).
        time_segment = match.group(1)  # e.g., "004408"

        # Split the time segment into hours, minutes, and seconds.
        # We're assuming here that the time is represented in a 'hhmmss' format.
        hours, remainder = divmod(int(time_segment), 10000)
        minutes, seconds = divmod(remainder, 100)

        formatted_time = hours * 3600 + minutes * 60 + seconds
        return formatted_time
    else:
        # If the regex finds no match, there's a format mismatch. Handle as appropriate.
        logging.info("The filename does not match the expected format.")
        return None

def process_directory(output_path, merge_subtitles=False):
    # Gather all JSON files in the directory
    json_files = sorted([file for file in os.listdir(TMP_DIR) if file.endswith('.json')])
    logging.info(f"Found {len(json_files)} speech recognition JSON file(s) for processing.")

    try:
        logging.info(f"Processing speech recognition JSON files")
        srt_content = create_srt_content(json_files)
        logging.info(f"Completed processing speech recognition JSON files")

        if merge_subtitles and os.path.exists(output_path):
            # If the merge flag is set, merge the new subtitles with the existing ones.
            logging.info(f"Merging generated subtitles with existing ones")
            with open(output_path, 'r', encoding='utf-8') as file:
                existing_srt_content = file.read()
            srt_content = merge_srt_content(existing_srt_content, srt_content)

        srt_output_file = open(output_path, 'w', encoding='utf-8')
        logging.info(f"Writing to output file: {output_path}")
        srt_output_file.write(srt_content.strip())
        srt_output_file.close()
    except Exception as e:
        logging.error(f"An error occurred while processing speech recognition JSON files: {str(e)}", exc_info=True)

    logging.info("All files have been processed.")

def generate_output(args):
    output_path = args.output or os.path.dirname(args.input)
    output_path = validate_output(output_path)
    merge_subtitles = args.merge
    process_directory(output_path, merge_subtitles)

if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description="Process audio segments.")
        parser.add_argument('-i', '--input', required=True, help="Input audio file (MP3 format).")
        parser.add_argument('-c', '--checkpoints', type=str, help="Checkpoints, either in comma-separated format hh:mm:ss (hours and minutes optional) or using pattern (ie 5s, 10m, 1h).")
        parser.add_argument('-s', '--segments', type=str, help="Segments to process in start-end format (00:50-13:57) or using pattern (ie 5s, 10m, 1h).")
        parser.add_argument('-l', '--language', type=str, help="Language of the audio.")
        parser.add_argument('-o', '--output', type=str, help="Output SRT file path (if no name is given and only a path, then a default name will be used). If not provided at all, then the output location will be the same one as the input.")
        parser.add_argument('-m', '--merge', action='store_true', help='If defined, it includes the new generated subtitles into the existing SRT file defined in the output parameter (if provided).')
        args = parser.parse_args()
        process_input(args)
        generate_output(args)
    except Exception as e:
        logging.error(f"An error occurred while processing the audio file: {str(e)}", exc_info=True)
    finally:
        shutil.rmtree(TMP_DIR)
        logging.info("Clean exit.")
        chrono.stop()
        chrono.print_duration()

# TODO: modularize code
# TODO: implement unit tests
# TODO: record demo video and put it in README.md (youtube link?)
# TODO: when provided input is video, extract audio from it
# TODO: clean input audio file
# TODO: translate generated srt to other languages
