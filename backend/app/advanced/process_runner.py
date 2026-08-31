from __future__ import annotations

import ctypes
import math
import os
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from threading import Thread
from time import monotonic
from typing import BinaryIO, Protocol


_STREAM_CHUNK_BYTES = 64 * 1024
_PROCESS_POLL_SECONDS = 0.01
_CLEANUP_TIMEOUT_SECONDS = 2.0


class CancellationSignal(Protocol):
    @property
    def is_cancelled(self) -> bool: ...


@dataclass(frozen=True)
class ProcessResourceLimits:
    """Server-owned resource budgets for one command process tree."""

    max_processes: int = 8
    max_memory_bytes: int = 512 * 1024 * 1024
    max_cpu_seconds: float = 30.0

    def __post_init__(self) -> None:
        for field_name in ("max_processes", "max_memory_bytes"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        if (
            isinstance(self.max_cpu_seconds, bool)
            or not isinstance(self.max_cpu_seconds, (int, float))
            or not math.isfinite(self.max_cpu_seconds)
            or self.max_cpu_seconds <= 0
        ):
            raise ValueError("max_cpu_seconds must be positive and finite")


@dataclass(frozen=True)
class BoundedProcessResult:
    stdout: bytes = field(repr=False)
    stderr: bytes = field(repr=False)
    return_code: int | None
    truncated: bool
    observed_output_bytes: int
    termination_reason: str
    resource_limit: str | None
    process_scope: str
    process_tree_cleaned: bool
    output_read_succeeded: bool


class ProcessStartError(RuntimeError):
    """The controlled process boundary could not be established."""


class ProcessMonitorError(RuntimeError):
    """The process-tree resource monitor became unavailable."""


@dataclass
class _BoundedCapture:
    limit: int
    payload: bytearray = field(default_factory=bytearray)
    observed_bytes: int = 0
    read_succeeded: bool = True

    def drain(self, stream: BinaryIO) -> None:
        try:
            while True:
                chunk = stream.read(_STREAM_CHUNK_BYTES)
                if not chunk:
                    return
                self.observed_bytes += len(chunk)
                remaining = self.limit - len(self.payload)
                if remaining > 0:
                    self.payload.extend(chunk[:remaining])
        except OSError:
            self.read_succeeded = False


@dataclass(frozen=True)
class _ResourceUsage:
    process_count: int
    memory_bytes: int
    cpu_seconds: float


class _ProcessTree(Protocol):
    scope: str

    def bind(self, process: subprocess.Popen[bytes]) -> None: ...

    def usage(self) -> _ResourceUsage | None: ...

    def close(self) -> bool: ...

    def cleanup(
        self,
        process: subprocess.Popen[bytes],
        *,
        terminate: bool,
    ) -> bool: ...


class _WindowsProcessTree:
    scope = "windows_job"

    def __init__(self) -> None:
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_functions()
        self._handle = self._kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise ProcessStartError("process resource boundary is unavailable")
        information = _JobObjectExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        if not self._kernel32.SetInformationJobObject(
            self._handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            self._close_handle()
            raise ProcessStartError("process resource boundary is unavailable")

    def _configure_functions(self) -> None:
        self._kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self._kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self._kernel32.SetInformationJobObject.restype = wintypes.BOOL
        self._kernel32.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
        ]
        self._kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        self._kernel32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        self._kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self._kernel32.TerminateJobObject.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL

    def bind(self, process: subprocess.Popen[bytes]) -> None:
        process_handle = wintypes.HANDLE(int(process._handle))  # type: ignore[attr-defined]
        if not self._kernel32.AssignProcessToJobObject(
            self._handle,
            process_handle,
        ):
            raise ProcessStartError("process resource boundary is unavailable")

    def usage(self) -> _ResourceUsage | None:
        accounting = _JobObjectBasicAccountingInformation()
        if not self._kernel32.QueryInformationJobObject(
            self._handle,
            _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
            ctypes.byref(accounting),
            ctypes.sizeof(accounting),
            None,
        ):
            raise ProcessMonitorError("process resource accounting is unavailable")
        extended = _JobObjectExtendedLimitInformation()
        if not self._kernel32.QueryInformationJobObject(
            self._handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(extended),
            ctypes.sizeof(extended),
            None,
        ):
            raise ProcessMonitorError("process resource accounting is unavailable")
        return _ResourceUsage(
            process_count=int(accounting.ActiveProcesses),
            memory_bytes=int(extended.PeakJobMemoryUsed),
            cpu_seconds=(
                int(accounting.TotalUserTime) + int(accounting.TotalKernelTime)
            )
            / 10_000_000,
        )

    def cleanup(
        self,
        process: subprocess.Popen[bytes],
        *,
        terminate: bool,
    ) -> bool:
        succeeded = True
        if terminate and self._handle:
            succeeded = bool(self._kernel32.TerminateJobObject(self._handle, 1))
        succeeded = self._close_handle() and succeeded
        if process.poll() is None:
            try:
                process.wait(timeout=_CLEANUP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                succeeded = False
        return succeeded and process.poll() is not None

    def close(self) -> bool:
        return self._close_handle()

    def _close_handle(self) -> bool:
        if not self._handle:
            return True
        handle = self._handle
        self._handle = None
        return bool(self._kernel32.CloseHandle(handle))


class _LinuxProcessTree:
    scope = "linux_process_group"

    def __init__(self) -> None:
        self._process_group_id: int | None = None
        self._clock_ticks = os.sysconf("SC_CLK_TCK")

    def bind(self, process: subprocess.Popen[bytes]) -> None:
        self._process_group_id = process.pid

    def usage(self) -> _ResourceUsage | None:
        process_group_id = self._process_group_id
        if process_group_id is None:
            return None
        process_count = 0
        memory_bytes = 0
        cpu_ticks = 0
        try:
            entries = tuple(Path("/proc").iterdir())
        except OSError as error:
            raise ProcessMonitorError(
                "process resource accounting is unavailable"
            ) from error
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                stat = (entry / "stat").read_text(encoding="utf-8")
                fields = stat[stat.rfind(")") + 2 :].split()
                if int(fields[2]) != process_group_id:
                    continue
                process_count += 1
                cpu_ticks += int(fields[11]) + int(fields[12])
                for line in (entry / "status").read_text(
                    encoding="utf-8"
                ).splitlines():
                    if line.startswith("VmRSS:"):
                        memory_bytes += int(line.split()[1]) * 1024
                        break
            except (FileNotFoundError, PermissionError, OSError, ValueError):
                continue
        return _ResourceUsage(
            process_count=process_count,
            memory_bytes=memory_bytes,
            cpu_seconds=cpu_ticks / self._clock_ticks,
        )

    def cleanup(
        self,
        process: subprocess.Popen[bytes],
        *,
        terminate: bool,
    ) -> bool:
        process_group_id = self._process_group_id
        succeeded = True
        if process_group_id is not None:
            try:
                os.killpg(process_group_id, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                succeeded = False
        if process.poll() is None:
            try:
                process.wait(timeout=_CLEANUP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                succeeded = False
        return succeeded and process.poll() is not None

    def close(self) -> bool:
        return True


if os.name == "nt":
    class _JobObjectBasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]


    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]


    class _JobObjectExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JobObjectBasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]


    class _JobObjectBasicAccountingInformation(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_int64),
            ("TotalKernelTime", ctypes.c_int64),
            ("ThisPeriodTotalUserTime", ctypes.c_int64),
            ("ThisPeriodTotalKernelTime", ctypes.c_int64),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]


_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


def run_bounded_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    max_output_bytes: int,
    resources: ProcessResourceLimits,
    cancellation: CancellationSignal | None = None,
) -> BoundedProcessResult:
    """Run one command with bounded pipe capture and process-tree ownership."""
    tree = _create_process_tree()
    launch_options: dict[str, object]
    if os.name == "nt":
        launch_options = {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
        }
    else:
        launch_options = {"start_new_session": True}
    try:
        process = subprocess.Popen(
            tuple(argv),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=dict(environment),
            **launch_options,
        )
    except (FileNotFoundError, PermissionError, OSError, subprocess.SubprocessError) as error:
        tree.close()
        raise ProcessStartError("controlled command could not be started") from error
    try:
        tree.bind(process)
    except ProcessStartError:
        tree.close()
        _fallback_process_cleanup(process)
        raise

    assert process.stdout is not None
    assert process.stderr is not None
    stdout_capture = _BoundedCapture(max_output_bytes)
    stderr_capture = _BoundedCapture(max_output_bytes)
    readers = (
        Thread(
            target=stdout_capture.drain,
            args=(process.stdout,),
            name="code-agent-stdout",
            daemon=True,
        ),
        Thread(
            target=stderr_capture.drain,
            args=(process.stderr,),
            name="code-agent-stderr",
            daemon=True,
        ),
    )
    for reader in readers:
        reader.start()

    deadline = monotonic() + timeout_seconds
    termination_reason = "exited"
    resource_limit: str | None = None
    while process.poll() is None:
        if cancellation is not None and cancellation.is_cancelled:
            termination_reason = "cancelled"
            break
        try:
            resource_limit = _exceeded_resource(tree.usage(), resources)
        except ProcessMonitorError:
            termination_reason = "resource_monitor_failed"
            break
        if resource_limit is not None:
            termination_reason = "resource_limit"
            break
        remaining = deadline - monotonic()
        if remaining <= 0:
            termination_reason = "timeout"
            break
        try:
            process.wait(timeout=min(_PROCESS_POLL_SECONDS, remaining))
        except subprocess.TimeoutExpired:
            pass

    return_code = process.poll()
    process_tree_cleaned = tree.cleanup(
        process,
        terminate=termination_reason != "exited" or return_code is None,
    )
    if return_code is None:
        return_code = process.poll()
    for reader in readers:
        reader.join(timeout=_CLEANUP_TIMEOUT_SECONDS)
    output_read_succeeded = (
        all(not reader.is_alive() for reader in readers)
        and stdout_capture.read_succeeded
        and stderr_capture.read_succeeded
    )
    if not readers[0].is_alive():
        process.stdout.close()
    if not readers[1].is_alive():
        process.stderr.close()

    stdout, stderr = _truncate_output(
        bytes(stdout_capture.payload),
        bytes(stderr_capture.payload),
        max_output_bytes,
    )
    observed_output_bytes = (
        stdout_capture.observed_bytes + stderr_capture.observed_bytes
    )
    return BoundedProcessResult(
        stdout=stdout,
        stderr=stderr,
        return_code=return_code,
        truncated=observed_output_bytes > max_output_bytes,
        observed_output_bytes=observed_output_bytes,
        termination_reason=termination_reason,
        resource_limit=resource_limit,
        process_scope=tree.scope,
        process_tree_cleaned=process_tree_cleaned,
        output_read_succeeded=output_read_succeeded,
    )


def _create_process_tree() -> _ProcessTree:
    try:
        if os.name == "nt":
            return _WindowsProcessTree()
        if sys.platform.startswith("linux"):
            return _LinuxProcessTree()
    except (AttributeError, OSError, ValueError) as error:
        raise ProcessStartError(
            "controlled process resource boundary is unavailable"
        ) from error
    raise ProcessStartError("controlled process platform is unsupported")


def _exceeded_resource(
    usage: _ResourceUsage | None,
    limits: ProcessResourceLimits,
) -> str | None:
    if usage is None:
        return None
    if usage.process_count > limits.max_processes:
        return "process_count"
    if usage.memory_bytes > limits.max_memory_bytes:
        return "memory"
    if usage.cpu_seconds > limits.max_cpu_seconds:
        return "cpu"
    return None


def _fallback_process_cleanup(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        taskkill = system_root / "System32" / "taskkill.exe"
        if taskkill.is_file():
            try:
                subprocess.run(
                    (str(taskkill), "/PID", str(process.pid), "/T", "/F"),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    shell=False,
                    timeout=_CLEANUP_TIMEOUT_SECONDS,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        if process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=_CLEANUP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()


def _truncate_output(
    stdout: bytes,
    stderr: bytes,
    limit: int,
) -> tuple[bytes, bytes]:
    kept_stdout = stdout[:limit]
    remaining = limit - len(kept_stdout)
    return kept_stdout, stderr[:remaining]
