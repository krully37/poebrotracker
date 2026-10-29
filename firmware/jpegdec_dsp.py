# JPEGDEC's ESP32-S3 SIMD code includes esp-dsp and Xtensa headers that are not on the library
# include path.
# (Done here because ${platformio.packages_dir} loses its backslashes in build_flags on Windows.)
Import("env")
from os.path import join

libs = env.PioPlatform().get_package_dir("framework-arduinoespressif32-esp32s3-libs")
dsp = join(libs, "include", "espressif__esp-dsp", "modules")
env.Append(CPPPATH=[join(dsp, "fft", "include"), join(dsp, "common", "include"),
                    join(libs, "include", "xtensa", "esp32s3", "include")])
