# Performance tooling shared by the Sub0 family (Sub0Perf, and every library that benchmarks).
#
#   sub0perf_target_perf_options(<target>)
#       Applies the profiling, vectorization-report and native-architecture options to a target.
#   (sub0math_target_deterministic_fp, the no-FMA-contraction option, is Sub0Math's: cmake/Sub0MathFp.cmake there.)
#   sub0perf_add_benchmark(<target> <sources>... [METRICS <spec>] [SMOKE_TEST])
#       Builds a nanobench executable using tools/perf/bench_runner.hpp, plus these targets:
#         <target>_json             run it once and write build/perf/<target>.json (nanobench format)
#         <target>_runs             SUB0PERF_BENCH_REPEATS interleaved, calibrated rounds -> <target>.samples.json
#         <target>_check            judge those rounds against perf/baselines/<host>.json; fails on a regression
#         <target>_baseline         record perf/baselines/<host>.json from the same rounds (needs a reason once
#                                   a baseline exists: bench_check.py baseline --reason ...)
#       The pre-push gate and the after-build check run at the quick level (a time budget, SUB0PERF_QUICK_BUDGET;
#       pairs and controls always, the other benchmarks rotating) unless the push carries a tag matching
#       SUB0PERF_FULL_REFS or SUB0PERF_LEVEL=full is set: docs/PERFORMANCE.md, "Levels".
#       and installs the pre-push gate and post-checkout hooks (SUB0PERF_GIT_HOOKS=AUTO|ON|OFF; AUTO: main checkout with a committed baseline, never on CI),
#       and, unless SUB0PERF_ON_BUILD is OFF, a quick check after every rebuild of <target>
#       (its code or a header it uses changed), reporting regressions and progressions implicitly.
#         <target>_compare          interleaved A/B (>= 10 rounds) of this build against the newest kept build that differs
#                                   (.git/sub0perf/bins), or SUB0PERF_COMPARE_AGAINST=<exe>; SUB0PERF_COMPARE_FILTER=<text>
#                                   limits it; brief output under SUB0PERF_OUTPUT=brief (docs/PERF_LOOP.md)
#       SMOKE_TEST: registers ctest test <target>_smoke (`<target> --smoke`: every workload once, exit status only).
#       METRICS <spec>: <spec> (relative to the project root, e.g. perf/metrics.json) holds the deterministic metrics the
#       executable reports with BenchRunner::metric(); registers ctest test <target>_metrics (`bench_check.py metrics`)
#       and the target <target>_metrics_accept (moves the failing and new metrics to the measured values, never an xfail one, editing
#       the spec in place; SUB0PERF_ACCEPT_METRIC="name;name" accepts just those and clears their xfail; reason in SUB0PERF_REASON).
#       Both tests carry the ctest label "smoke" and never time anything, so they are safe in `ctest` and CI.
#         <target>_vtune_hotspots   VTune hotspots      (SUB0PERF_PROFILE_FILTER, _SECONDS)
#         <target>_vtune_uarch      VTune microarchitecture exploration
#         <target>_advisor_roofline Intel Advisor vectorization survey and roofline
#         <target>_perf_record      Linux perf sampling with call graphs
#
#   sub0perf_add_test(<name> [FULL] COMMAND <command> [args...])
#       add_test() that can label a long suite FULL (ctest label "full"). `ctest -LE full` is then the quick
#       run for everyday work; plain `ctest` runs everything (milestones, CI). Tests made by a discovery macro
#       are labelled with its own argument: gtest_discover_tests(<t> PROPERTIES LABELS full) or
#       doctest_discover_tests(<t> ADD_LABELS 1 TEST_SUFFIX ...) / catch_discover_tests(<t> PROPERTIES LABELS full).
#   sub0perf_label_full_tests(<test>...)
#       Adds the "full" label to tests that already exist (same directory scope).
#
# Consumers include this file from the Sub0Perf source tree (CPM sets Sub0Perf_SOURCE_DIR).

include_guard(GLOBAL)

# Paths are resolved inside each function from CMAKE_CURRENT_FUNCTION_LIST_DIR: include_guard skips
# re-inclusion, so variables set here would not reach a consumer's directory scope.

# Transition (one release): the SUB0MATH_* names keep working. A setting declared here is a cache entry only while its old name is not
# defined; when a consumer defines the old name (set(SUB0MATH_PERF_ON_BUILD OFF CACHE ...), -DSUB0MATH_PERF_GIT_HOOKS=OFF), its value is
# used through a plain variable of the new name each run, so a stale cache entry of the new name never hides it. The new name wins when both
# are given. SUB0MATH_PERF_X is SUB0PERF_X; the other SUB0MATH_Y are SUB0PERF_Y.
macro(_sub0perf_setting name old default type doc)
    if(NOT DEFINED ${name} AND DEFINED ${old})
        set(${name} "${${old}}")
    elseif(NOT DEFINED ${old})
        set(${name} "${default}" CACHE ${type} "${doc}")
    endif()
endmacro()

_sub0perf_setting(SUB0PERF_PROFILE_FLAGS SUB0MATH_PROFILE_FLAGS OFF BOOL "Debug info and frame pointers in optimised builds, for profilers")
_sub0perf_setting(SUB0PERF_VECTORIZATION_REPORT SUB0MATH_VECTORIZATION_REPORT OFF BOOL "Emit compiler vectorization remarks")
_sub0perf_setting(SUB0PERF_NATIVE_ARCH SUB0MATH_NATIVE_ARCH OFF BOOL "Tune for the build machine's CPU (local experiments only)")
_sub0perf_setting(SUB0PERF_PROFILE_FILTER SUB0MATH_PROFILE_FILTER "" STRING "Benchmark name substring the profiling targets run")
_sub0perf_setting(SUB0PERF_PROFILE_SECONDS SUB0MATH_PROFILE_SECONDS "10" STRING "Soak seconds per benchmark under a profiler")
_sub0perf_setting(SUB0PERF_BENCH_REPEATS SUB0MATH_BENCH_REPEATS "5" STRING "Interleaved rounds per budget check (tools/perf/bench_check.py)")
_sub0perf_setting(SUB0PERF_ON_BUILD SUB0MATH_PERF_ON_BUILD "REPORT" STRING
    "After a benchmark executable is rebuilt: OFF, REPORT (print regressions and progressions) or ENFORCE (fail the build on a regression)")
_sub0perf_setting(SUB0PERF_QUICK_ROUNDS SUB0MATH_PERF_QUICK_ROUNDS "3" STRING "Rounds for the after-build check (noisy benchmarks get up to twice as many)")
_sub0perf_setting(SUB0PERF_QUICK_BUDGET SUB0MATH_PERF_QUICK_BUDGET "90" STRING
    "Target seconds of measuring for the quick level (the pre-push gate and the after-build check); 0 = no budget. Override per run with SUB0PERF_BUDGET or --budget")
_sub0perf_setting(SUB0PERF_FULL_REFS SUB0MATH_PERF_FULL_REFS "v*;milestone/*" STRING
    "Tag-name patterns (a list): pushing a matching tag runs the pre-push gate at the full level. Override a run with SUB0PERF_LEVEL=full|quick")
_sub0perf_setting(SUB0PERF_QUICK_EPOCHS SUB0MATH_PERF_QUICK_EPOCHS "0" STRING
    "nanobench epochs in the after-build check; 0 = default, the same method as baselines and records")
_sub0perf_setting(SUB0PERF_GIT_HOOKS SUB0MATH_PERF_GIT_HOOKS "AUTO" STRING
    "Pre-push performance gate and post-checkout note in this repository's git hooks: ON, OFF, or AUTO (the default: on only from the main checkout (a linked worktree shares its hooks and gate configuration: docs/PERFORMANCE.md), where perf/baselines/<host>.json exists, and never on CI)")
if(DEFINED CACHE{SUB0PERF_ON_BUILD})
    set_property(CACHE SUB0PERF_ON_BUILD PROPERTY STRINGS OFF REPORT ENFORCE)
endif()
if(DEFINED CACHE{SUB0PERF_GIT_HOOKS})
    set_property(CACHE SUB0PERF_GIT_HOOKS PROPERTY STRINGS AUTO ON OFF)
endif()
# SUB0MATH_PERF_PINS is a list a consumer sets as a plain variable; the new name SUB0PERF_PINS is read first.
if(NOT DEFINED SUB0PERF_PINS AND DEFINED SUB0MATH_PERF_PINS)
    set(SUB0PERF_PINS "${SUB0MATH_PERF_PINS}")
endif()
# The compare and accept targets declare their settings in sub0perf_add_benchmark, through the same macro.

# Where the scripts are, for shells and CI: `python "$(cat build/sub0perf_tooling_dir.txt)/profile.py" ...`.
# CPM may place Sub0Perf anywhere, so consumers should not hard-code the path.
get_filename_component(_sub0perf_tooling_dir "${CMAKE_CURRENT_LIST_DIR}/../tools/perf" ABSOLUTE)
file(WRITE "${CMAKE_BINARY_DIR}/sub0perf_tooling_dir.txt" "${_sub0perf_tooling_dir}")
file(WRITE "${CMAKE_BINARY_DIR}/sub0math_tooling_dir.txt" "${_sub0perf_tooling_dir}")  # the old name, for one release

cmake_host_system_information(RESULT _sub0perf_host QUERY HOSTNAME)
string(TOLOWER "${_sub0perf_host}" _sub0perf_host)
if(NOT DEFINED SUB0PERF_HOST AND NOT DEFINED SUB0MATH_PERF_HOST)
    if(DEFINED ENV{SUB0PERF_HOST})
        set(_sub0perf_host "$ENV{SUB0PERF_HOST}")   # the baseline name a shell chose; the cache variable still wins
    elseif(DEFINED ENV{SUB0MATH_PERF_HOST})
        set(_sub0perf_host "$ENV{SUB0MATH_PERF_HOST}")
    endif()
endif()
_sub0perf_setting(SUB0PERF_HOST SUB0MATH_PERF_HOST "${_sub0perf_host}" STRING "Baseline name in perf/baselines/")

function(sub0perf_target_perf_options target)
    if(SUB0PERF_PROFILE_FLAGS)
        target_compile_options(${target} PRIVATE
            $<$<CXX_COMPILER_ID:MSVC>:/Zi /Oy->
            $<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-g -fno-omit-frame-pointer>)
        target_link_options(${target} PRIVATE $<$<CXX_COMPILER_ID:MSVC>:/DEBUG>)
    endif()
    if(SUB0PERF_VECTORIZATION_REPORT)
        target_compile_options(${target} PRIVATE
            $<$<CXX_COMPILER_ID:MSVC>:/Qvec-report:2>
            $<$<CXX_COMPILER_ID:GNU>:-fopt-info-vec-optimized -fopt-info-vec-missed>
            $<$<CXX_COMPILER_ID:Clang,AppleClang>:-Rpass=loop-vectorize|slp-vectorizer
                -Rpass-missed=loop-vectorize -Rpass-analysis=loop-vectorize>)
    endif()
    if(SUB0PERF_NATIVE_ARCH)
        target_compile_options(${target} PRIVATE
            $<$<CXX_COMPILER_ID:MSVC>:/arch:AVX2>
            $<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-march=native>)
    endif()
endfunction()

# Quality gates come in the same two levels as the performance gate. A suite that takes long is labelled
# "full"; everyday runs exclude it (ctest -LE full, or the "quick" test preset), milestones and CI run everything.
set(SUB0PERF_FULL_TEST_LABEL "full")

function(sub0perf_label_full_tests)
    foreach(test IN LISTS ARGN)
        if(NOT TEST ${test})
            message(FATAL_ERROR "sub0perf_label_full_tests: no test named '${test}' in this directory")
        endif()
        set_property(TEST ${test} APPEND PROPERTY LABELS "${SUB0PERF_FULL_TEST_LABEL}")
    endforeach()
endfunction()

function(sub0perf_add_test name)
    cmake_parse_arguments(PARSE_ARGV 1 T "FULL" "" "COMMAND")
    if(NOT T_COMMAND)
        message(FATAL_ERROR "sub0perf_add_test(<name> [FULL] COMMAND <command> [args...]): COMMAND is required")
    endif()
    add_test(NAME ${name} COMMAND ${T_COMMAND})
    if(T_FULL)
        sub0perf_label_full_tests(${name})
    endif()
endfunction()

function(sub0perf_add_benchmark target)
    cmake_parse_arguments(PARSE_ARGV 1 B "SMOKE_TEST" "METRICS" "")
    set(sources ${B_UNPARSED_ARGUMENTS})
    if(NOT sources)
        message(FATAL_ERROR "sub0perf_add_benchmark(<target> <sources>... [METRICS <spec>] [SMOKE_TEST]): sources are required")
    endif()
    get_filename_component(tooling "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../tools/perf" ABSOLUTE)
    get_filename_component(vendor "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../vendor" ABSOLUTE)
    add_executable(${target} ${sources})
    target_include_directories(${target} SYSTEM PRIVATE "${tooling}" "${vendor}")
    target_compile_features(${target} PRIVATE cxx_std_23)
    sub0perf_target_perf_options(${target})

    # Smoke: every workload once, exit status only (never timing), so it belongs in ctest and CI.
    if(B_SMOKE_TEST)
        add_test(NAME ${target}_smoke COMMAND $<TARGET_FILE:${target}> --smoke)
        set_tests_properties(${target}_smoke PROPERTIES LABELS "smoke")
    endif()

    find_package(Python3 COMPONENTS Interpreter QUIET)
    if(NOT Python3_Interpreter_FOUND)
        return()
    endif()
    set(results "${CMAKE_BINARY_DIR}/perf/${target}.json")
    set(samples "${CMAKE_BINARY_DIR}/perf/${target}.samples.json")
    set(baseline "${PROJECT_SOURCE_DIR}/perf/baselines/${SUB0PERF_HOST}.json")
    set(check "${tooling}/bench_check.py")
    # Records and baselines carry the host name the baseline file is named by (SUB0PERF_HOST), not the machine's own name.
    set(host_env ${CMAKE_COMMAND} -E env "SUB0PERF_HOST=${SUB0PERF_HOST}" "SUB0MATH_PERF_HOST=${SUB0PERF_HOST}")
    set(profile "${tooling}/profile.py")

    add_custom_target(${target}_json
        COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/perf"
        COMMAND $<TARGET_FILE:${target}> --json "${results}"
        DEPENDS ${target} USES_TERMINAL VERBATIM)
    # Interleaved, calibrated, load-aware rounds: see tools/perf/bench_check.py.
    add_custom_target(${target}_runs
        COMMAND ${host_env} ${Python3_EXECUTABLE} "${check}" run --exe $<TARGET_FILE:${target}> --out "${samples}"
                --rounds ${SUB0PERF_BENCH_REPEATS}
        DEPENDS ${target} USES_TERMINAL VERBATIM)
    add_custom_target(${target}_check
        COMMAND ${Python3_EXECUTABLE} "${check}" check --results "${samples}" --baseline "${baseline}"
        DEPENDS ${target}_runs USES_TERMINAL VERBATIM)
    add_custom_target(${target}_baseline
        COMMAND ${host_env} ${Python3_EXECUTABLE} "${check}" baseline --results "${samples}" --baseline "${baseline}"
        DEPENDS ${target}_runs USES_TERMINAL VERBATIM)

    # Interleaved A/B against a kept build, or SUB0PERF_COMPARE_AGAINST (docs/PERF_LOOP.md, step 3).
    _sub0perf_setting(SUB0PERF_COMPARE_AGAINST SUB0MATH_COMPARE_AGAINST "" FILEPATH "<target>_compare: compare against this executable instead of the newest kept build")
    _sub0perf_setting(SUB0PERF_COMPARE_FILTER SUB0MATH_COMPARE_FILTER "" STRING "<target>_compare: only benchmarks (and their groups) whose name contains this text")
    set(compare_args --exe $<TARGET_FILE:${target}> --target ${target} --repo "${PROJECT_SOURCE_DIR}" --rounds 10)
    if(SUB0PERF_COMPARE_AGAINST)
        list(APPEND compare_args --against "${SUB0PERF_COMPARE_AGAINST}")
    else()
        list(APPEND compare_args --kept)
    endif()
    if(SUB0PERF_COMPARE_FILTER)
        list(APPEND compare_args --filter "${SUB0PERF_COMPARE_FILTER}")
    endif()
    add_custom_target(${target}_compare
        COMMAND ${Python3_EXECUTABLE} "${check}" compare ${compare_args}
        DEPENDS ${target} USES_TERMINAL VERBATIM)

    # Deterministic metrics (exact or maximum values; no timing): a ctest test and an accept target.
    if(B_METRICS)
        if(IS_ABSOLUTE "${B_METRICS}")
            set(metrics_spec "${B_METRICS}")
        else()
            set(metrics_spec "${PROJECT_SOURCE_DIR}/${B_METRICS}")
        endif()
        set(metrics_out "${CMAKE_BINARY_DIR}/perf/${target}.metrics.json")
        add_test(NAME ${target}_metrics
                 COMMAND ${Python3_EXECUTABLE} "${check}" metrics --exe $<TARGET_FILE:${target}> --spec "${metrics_spec}"
                         --out "${metrics_out}")
        set_tests_properties(${target}_metrics PROPERTIES LABELS "smoke")
        # Without SUB0PERF_ACCEPT_METRIC the failing and new metrics are accepted (--all-changed), never an xfail one; naming a
        # metric (a ;-list) accepts exactly those, and clears the xfail marker of a named metric. The spec is edited in place.
        _sub0perf_setting(SUB0PERF_ACCEPT_METRIC SUB0MATH_ACCEPT_METRIC "" STRING "<target>_metrics_accept: accept only these metrics (;-list); an xfail is cleared only for a named one")
        if(SUB0PERF_ACCEPT_METRIC)
            set(accept_which --metric ${SUB0PERF_ACCEPT_METRIC})
        else()
            set(accept_which --all-changed)
        endif()
        add_custom_target(${target}_metrics_accept
            COMMAND ${Python3_EXECUTABLE} "${check}" accept --exe $<TARGET_FILE:${target}> --spec "${metrics_spec}"
                    --out "${metrics_out}" ${accept_which}
            DEPENDS ${target} USES_TERMINAL VERBATIM)
    endif()

    # Implicit report: the executable relinks only when its code, or a header it uses, changed.
    if(NOT SUB0PERF_ON_BUILD STREQUAL "OFF")
        set(mode_args --report-only)
        if(SUB0PERF_ON_BUILD STREQUAL "ENFORCE")
            set(mode_args "")
        endif()
        add_custom_command(TARGET ${target} POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E echo "perf: quick interleaved check of ${target} (SUB0PERF_ON_BUILD=${SUB0PERF_ON_BUILD})"
            COMMAND ${host_env} ${Python3_EXECUTABLE} "${check}" auto --exe $<TARGET_FILE:${target}> --baseline "${baseline}"
                    --rounds ${SUB0PERF_QUICK_ROUNDS} --epochs ${SUB0PERF_QUICK_EPOCHS}
                    --budget ${SUB0PERF_QUICK_BUDGET}
                    --out "${CMAKE_BINARY_DIR}/perf/${target}.quick.json" ${mode_args}
                    --record --target ${target} --repo "${PROJECT_SOURCE_DIR}"
            VERBATIM)
    endif()

    # Pre-push gate: blocks a push whose benchmarks regressed against the committed baseline or the
    # local record of the commit it started from, unless the regression was accepted (bench_check.py accept).
    set(install_hooks "${SUB0PERF_GIT_HOOKS}")
    set(hook_keep "")
    if(install_hooks STREQUAL "AUTO")
        set(hook_keep --keep-existing)  # AUTO never repoints a gate whose build directory still exists; ON takes it over
        if(NOT DEFINED ENV{CI} AND IS_DIRECTORY "${PROJECT_SOURCE_DIR}/.git" AND EXISTS "${baseline}")
            set(install_hooks ON)
        else()
            set(install_hooks OFF)
        endif()
    endif()
    if(install_hooks AND EXISTS "${PROJECT_SOURCE_DIR}/.git")
        if(CMAKE_CONFIGURATION_TYPES)
            set(hook_config Release)
            set(hook_exe "${CMAKE_CURRENT_BINARY_DIR}/Release/${target}${CMAKE_EXECUTABLE_SUFFIX}")
        else()
            set(hook_config "")
            set(hook_exe "${CMAKE_CURRENT_BINARY_DIR}/${target}${CMAKE_EXECUTABLE_SUFFIX}")
        endif()
        # SUB0PERF_PINS: dependency pins the pre-push hook checks are on the dependency's remote, each
        # "file=cmake/Dependencies.cmake,var=X_REVISION,repo=owner/name[,checkout=../X][,name=X]" (docs/PERFORMANCE.md).
        set(pin_args "")
        foreach(pin IN LISTS SUB0PERF_PINS)
            list(APPEND pin_args --pin "${pin}")
        endforeach()
        execute_process(
            COMMAND ${Python3_EXECUTABLE} "${check}" install-hooks --repo "${PROJECT_SOURCE_DIR}" --build-dir "${CMAKE_BINARY_DIR}"
                    --target ${target} --exe "${hook_exe}" --baseline "${baseline}" --config "${hook_config}" ${pin_args}
                    --full-refs "${SUB0PERF_FULL_REFS}" --quick-budget ${SUB0PERF_QUICK_BUDGET} ${hook_keep}
            RESULT_VARIABLE hook_result)
        if(NOT hook_result EQUAL 0)
            message(WARNING "sub0perf: installing the git hooks failed (${hook_result})")
        endif()
    endif()

    foreach(analysis vtune-hotspots vtune-uarch advisor-roofline perf-record)
        string(REPLACE "-" "_" suffix "${analysis}")
        add_custom_target(${target}_${suffix}
            COMMAND ${Python3_EXECUTABLE} "${profile}" ${analysis} --exe $<TARGET_FILE:${target}>
                    --filter "${SUB0PERF_PROFILE_FILTER}" --seconds ${SUB0PERF_PROFILE_SECONDS}
                    --out "${CMAKE_BINARY_DIR}/profiles"
            DEPENDS ${target} USES_TERMINAL VERBATIM)
    endforeach()
endfunction()

# The old function names, for one release: each says so once and forwards.
foreach(_sub0perf_fn IN ITEMS add_benchmark target_perf_options add_test label_full_tests)
    cmake_language(EVAL CODE "
        function(sub0math_${_sub0perf_fn})
            message(DEPRECATION \"sub0math_${_sub0perf_fn} is renamed sub0perf_${_sub0perf_fn}\")
            sub0perf_${_sub0perf_fn}(\${ARGV})
        endfunction()")
endforeach()
