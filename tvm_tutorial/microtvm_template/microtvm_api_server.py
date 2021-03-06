import pathlib
import typing
import os
import shutil
import tarfile
import subprocess
import fcntl
import select
import time

from tvm.micro.project_api import server

API_SERVER_DIR = pathlib.Path(os.path.dirname(__file__) or os.path.getcwd())

PROJECT_OPTIONS=[
    server.ProjectOption(
        "project_type",
        help="Type of project to generate.",
        choices=("aot_demo", "host_driven"),
    ),
    server.ProjectOption(
        "verbose", 
        help="Run make with verbose output", 
        choices=(True, False)
    ),
]

PROJECT_DIR = pathlib.Path(os.path.dirname(__file__) or os.path.getcwd())
MODEL_LIBRARY_FORMAT_RELPATH = "model.tar"
IS_TEMPLATE = not os.path.exists(os.path.join(PROJECT_DIR, MODEL_LIBRARY_FORMAT_RELPATH))

class Handler(server.ProjectAPIHandler):
    def __init__(self):

        super(Handler, self).__init__()
        self._proc = None

    def server_info_query(self, tvm_version):
        return server.ServerInfo(
            platform_name="utvm_example",
            is_template=IS_TEMPLATE,
            model_library_format_path="" if IS_TEMPLATE else PROJECT_DIR / MODEL_LIBRARY_FORMAT_RELPATH,
            project_options=PROJECT_OPTIONS,
        )

    # These files and directories will be recursively copied into generated projects from the CRT.
    CRT_COPY_ITEMS = ("include", "Makefile", "src")

    # The build target given to make
    BUILD_TARGET = "build/main"

    def generate_project(
        self,
        model_library_format_path: pathlib.Path,
        standalone_crt_dir: pathlib.Path,
        project_dir: pathlib.Path,
        options: dict,
    ):
        print("Generating project")
        print("  MLF Path:", model_library_format_path)
        print("  CRT Dir:", standalone_crt_dir)
        print("  Project Dir:", project_dir)
        print("  Options:", options)

        # Make project directory.
        project_dir.mkdir(parents=True)

        # Copy ourselves to the generated project. TVM may perform further build steps on the generated project
        # by launching the copy.
        shutil.copy2(__file__, project_dir / os.path.basename(__file__))

        # Place Model Library Format tarball in the special location, which this script uses to decide
        # whether it's being invoked in a template or generated project.
        project_model_library_format_path = project_dir / MODEL_LIBRARY_FORMAT_RELPATH
        shutil.copy2(model_library_format_path, project_model_library_format_path)

        # Extract Model Library Format tarball.into <project_dir>/model.
        extract_path = project_dir / project_model_library_format_path.stem
        with tarfile.TarFile(project_model_library_format_path) as tf:
            os.makedirs(extract_path)
            tf.extractall(path=extract_path)

        # Populate CRT.
        crt_path = project_dir / "crt"
        os.mkdir(crt_path)
        for item in self.CRT_COPY_ITEMS:
            src_path = standalone_crt_dir / item
            dst_path = crt_path / item
            if os.path.isdir(src_path):
                shutil.copytree(src_path, dst_path)
            else:
                shutil.copy2(src_path, dst_path)

        project_type = options["project_type"]

        # Copy Makefile
        shutil.copy2(pathlib.Path(__file__).parent / "src" / project_type / "Makefile", project_dir / "Makefile")


        # Copy CRT-Runtime Config
        crt_config_dir = project_dir / "crt_config"
        crt_config_dir.mkdir()
        shutil.copy2(
            os.path.join(os.path.dirname(__file__),  "crt_config-template.h"),
            os.path.join(crt_config_dir, "crt_config.h"),
        )

        # Populate src/
        src_dir = os.path.join(project_dir, "src")
        os.mkdir(src_dir)
        shutil.copy2(
            os.path.join(os.path.dirname(__file__), "src", project_type, "main.cc"), os.path.join(src_dir, "main.cc")
        )


    def build(self, options: dict):
        print("Building project:", options)

        args = ["make"]
        if options.get("verbose"):
            args.append("VERBOSE=1")

        args.append(self.BUILD_TARGET)

        print("Build Command:", " ".join(args))

        subprocess.check_call(args, cwd=PROJECT_DIR)

    def flash(self, options: dict):
        print("Flashing project:", options)
        print("Flashing does nothing for virtual target")


    def _set_nonblock(self, fd):
        flag = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flag | os.O_NONBLOCK)
        new_flag = fcntl.fcntl(fd, fcntl.F_GETFL)
        assert (new_flag & os.O_NONBLOCK) != 0, "Cannot set file descriptor {fd} to non-blocking"

    def open_transport(self, options):
        self._proc = subprocess.Popen(
            [self.BUILD_TARGET], stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0
        )
        self._set_nonblock(self._proc.stdin.fileno())
        self._set_nonblock(self._proc.stdout.fileno())
        return server.TransportTimeouts(
            session_start_retry_timeout_sec=0,
            session_start_timeout_sec=0,
            session_established_timeout_sec=0,
        )

    def close_transport(self):
        if self._proc is not None:
            proc = self._proc
            self._proc = None
            proc.terminate()
            proc.wait()

    def _await_ready(self, rlist, wlist, timeout_sec=None, end_time=None):
        if timeout_sec is None and end_time is not None:
            timeout_sec = max(0, end_time - time.monotonic())

        rlist, wlist, xlist = select.select(rlist, wlist, rlist + wlist, timeout_sec)
        if not rlist and not wlist and not xlist:
            raise server.IoTimeoutError()

        return True

    def read_transport(self, n, timeout_sec):
        if self._proc is None:
            raise server.TransportClosedError()

        fd = self._proc.stdout.fileno()
        end_time = None if timeout_sec is None else time.monotonic() + timeout_sec

        try:
            self._await_ready([fd], [], end_time=end_time)
            to_return = os.read(fd, n)
        except BrokenPipeError:
            to_return = 0

        if not to_return:
            self.disconnect_transport()
            raise server.TransportClosedError()

        return to_return

    def write_transport(self, data, timeout_sec):
        if self._proc is None:
            raise server.TransportClosedError()

        fd = self._proc.stdin.fileno()
        end_time = None if timeout_sec is None else time.monotonic() + timeout_sec

        data_len = len(data)
        while data:
            self._await_ready([], [fd], end_time=end_time)
            try:
                num_written = os.write(fd, data)
            except BrokenPipeError:
                num_written = 0

            if not num_written:
                self.disconnect_transport()
                raise server.TransportClosedError()

            data = data[num_written:]


if __name__ == "__main__":
    server.main(Handler())