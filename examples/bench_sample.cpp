// Sample benchmark: shows BenchRunner, a hand-written reference pair and a deterministic metric.
#define ANKERL_NANOBENCH_IMPLEMENT
#include <bench_runner.hpp>

#include <array>
#include <cstddef>
#include <numeric>

namespace
{
constexpr std::size_t kCount = 1024;

std::array<double, kCount> makeData()
{
    std::array<double, kCount> data{};
    for (std::size_t i = 0; i < kCount; ++i)
        data[i] = static_cast<double>(i % 17) * 0.5;
    return data;
}
}  // namespace

int main(int argc, char** argv)
{
    sub0bench::BenchRunner runner(argc, argv, "Sub0Perf sample, 1024 elements per op");
    runner.metric("sizeof sample element", sizeof(double), "B");
    runner.bench().unit("1024 elements").minEpochIterations(30000);

    const auto data = makeData();

    // A pair: the hand-written reference first, the abstraction under test second (same name, different suffix).
    runner.run("sum of squares, hand-written loop", [&] {
        double sum = 0.0;
        for (std::size_t i = 0; i < kCount; ++i)
            sum += data[i] * data[i];
        ankerl::nanobench::doNotOptimizeAway(sum);
    });
    runner.run("sum of squares, std::inner_product", [&] {
        ankerl::nanobench::doNotOptimizeAway(std::inner_product(data.begin(), data.end(), data.begin(), 0.0));
    });

    // A second, trivial workload.
    runner.run("running sum, std::accumulate", [&] {
        ankerl::nanobench::doNotOptimizeAway(std::accumulate(data.begin(), data.end(), 0.0));
    });
    return runner.finish();
}
