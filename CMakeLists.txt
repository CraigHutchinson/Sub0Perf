cmake_minimum_required(VERSION 3.21)

# Detect if Sub0Perf is being included inside another project
if(DEFINED PROJECT_NAME)
    set(IS_SUBPROJECT ON)
endif()

project(Sub0Perf VERSION 0.1.0 LANGUAGES CXX)

# No git hooks in this repository: it has no timing gate of its own. Consumers choose for themselves.
if(NOT IS_SUBPROJECT)
    set(SUB0MATH_PERF_GIT_HOOKS OFF CACHE BOOL "Install the pre-push performance gate in this repository's git hooks" FORCE)
endif()

include(cmake/Sub0Perf.cmake)

# A sample benchmark exercises the module end to end: smoke and metrics ctest tests, no timing in CI.
if(NOT IS_SUBPROJECT)
    option(SUB0PERF_BUILD_EXAMPLES "Build the sample benchmark and its ctest tests" ON)
    if(SUB0PERF_BUILD_EXAMPLES)
        enable_testing()
        sub0math_add_benchmark(Sub0Perf_SampleBench examples/bench_sample.cpp METRICS examples/metrics.json SMOKE_TEST)
    endif()
endif()
