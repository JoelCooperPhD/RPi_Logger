import asyncio

import pytest

from rpi_logger.modules.Cameras2.runtime.record.csv_logger import CSV_HEADER, CSVLogger, CSVRecord


@pytest.mark.asyncio
async def test_csv_logger_writes_header_and_formats_row(tmp_path):
    csv_path = tmp_path / "session" / "cam.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.touch()

    logger = CSVLogger(trial_number=3, camera_label="cam_csv", flush_every=1)
    await logger.start(csv_path)
    logger.log_frame(
        CSVRecord(
            trial=3,
            frame_number=7,
            write_time_unix=1.1234567,
            monotonic_time=2.987654321,
            sensor_timestamp_ns=None,
            hardware_frame_number=None,
            dropped_since_last=None,
            total_hardware_drops=0,
            storage_queue_drops=0,
        )
    )
    await logger.stop()

    lines = csv_path.read_text().strip().splitlines()
    assert lines[0] == ",".join(CSV_HEADER)
    assert lines[1] == "3,7,1.123457,2.987654321,,,,0,0"


@pytest.mark.asyncio
async def test_csv_logger_respects_existing_header(tmp_path):
    csv_path = tmp_path / "session" / "cam.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(",".join(CSV_HEADER) + "\npreserved\n")

    logger = CSVLogger(trial_number=None, camera_label="cam_csv", flush_every=1)
    await logger.start(csv_path)
    logger.log_frame(
        CSVRecord(
            trial=None,
            frame_number=2,
            write_time_unix=10.0,
            monotonic_time=20.0,
            sensor_timestamp_ns=123,
            hardware_frame_number=5,
            dropped_since_last=1,
            total_hardware_drops=2,
            storage_queue_drops=3,
        )
    )
    await logger.stop()

    lines = csv_path.read_text().strip().splitlines()
    assert lines[0] == ",".join(CSV_HEADER)
    assert lines.count(",".join(CSV_HEADER)) == 1
    assert lines[1] == "preserved"
    assert lines[-1] == ",2,10.000000,20.000000000,123,5,1,2,3"
