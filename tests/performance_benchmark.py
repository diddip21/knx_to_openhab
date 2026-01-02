"""Performance benchmark comparing legacy vs refactored implementations."""
import time
import sys
import json
from pathlib import Path
from typing import Dict, List, Tuple
import tracemalloc

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import config
from src import gen_building_new
import ets_to_openhab


class PerformanceBenchmark:
    """Benchmark tool for comparing implementation performance."""
    
    def __init__(self):
        self.results = {
            'legacy': {},
            'refactored': {},
            'comparison': {}
        }
    
    def generate_test_data(self, num_floors: int = 2, num_rooms: int = 3, 
                          num_addresses: int = 10) -> Tuple[List, List]:
        """Generate synthetic test data for benchmarking."""
        floors = []
        all_addresses = []
        
        for f in range(num_floors):
            floor = {
                'Group name': f'Floor {f+1}',
                'Description': f'Test Floor {f+1}',
                'name_short': f'F{f+1}',
                'rooms': []
            }
            
            for r in range(num_rooms):
                room = {
                    'Group name': f'Room {r+1}',
                    'Description': f'Test Room {r+1}',
                    'name_short': f'R{r+1}',
                    'Addresses': []
                }
                
                # Add test addresses
                for a in range(num_addresses):
                    address = {
                        'Address': f'{f+1}/{r+1}/{a+1}',
                        'Group name': f'Device {a+1}',
                        'Description': 'Test device',
                        'DatapointType': 'DPST-1-1',  # Switch
                        'communication_object': []
                    }
                    room['Addresses'].append(address)
                    all_addresses.append(address)
                
                floor['rooms'].append(room)
            floors.append(floor)
        
        return floors, all_addresses
    
    def benchmark_legacy(self, floors: List, all_addresses: List) -> Dict:
        """Benchmark legacy implementation."""
        # Set up globals
        ets_to_openhab.floors = floors
        ets_to_openhab.all_addresses = all_addresses[:]
        ets_to_openhab.used_addresses = []
        ets_to_openhab.equipments = {}
        ets_to_openhab.export_to_influx = []
        ets_to_openhab.FENSTERKONTAKTE = []
        
        # Start memory tracking
        tracemalloc.start()
        start_time = time.perf_counter()
        
        # Run generation
        items, sitemap, things = ets_to_openhab.gen_building()
        
        # Measure performance
        end_time = time.perf_counter()
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        return {
            'execution_time': end_time - start_time,
            'memory_current_mb': current / 1024 / 1024,
            'memory_peak_mb': peak / 1024 / 1024,
            'items_lines': len(items.splitlines()),
            'things_lines': len(things.splitlines()),
            'sitemap_lines': len(sitemap.splitlines())
        }
    
    def benchmark_refactored(self, floors: List, all_addresses: List) -> Dict:
        """Benchmark refactored implementation."""
        # Start memory tracking
        tracemalloc.start()
        start_time = time.perf_counter()
        
        # Run generation
        items, sitemap, things = gen_building_new(floors, all_addresses[:], config)
        
        # Measure performance
        end_time = time.perf_counter()
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        return {
            'execution_time': end_time - start_time,
            'memory_current_mb': current / 1024 / 1024,
            'memory_peak_mb': peak / 1024 / 1024,
            'items_lines': len(items.splitlines()),
            'things_lines': len(things.splitlines()),
            'sitemap_lines': len(sitemap.splitlines())
        }
    
    def run_benchmark(self, test_sizes: List[Tuple[int, int, int]] = None):
        """Run complete benchmark suite."""
        if test_sizes is None:
            test_sizes = [
                (1, 2, 5),   # Small: 1 floor, 2 rooms, 5 addresses each
                (2, 3, 10),  # Medium: 2 floors, 3 rooms, 10 addresses each
                (3, 5, 20),  # Large: 3 floors, 5 rooms, 20 addresses each
            ]
        
        print("=" * 80)
        print("Performance Benchmark: Legacy vs Refactored Implementation")
        print("=" * 80)
        
        for i, (num_floors, num_rooms, num_addresses) in enumerate(test_sizes):
            test_name = f"Test {i+1}: {num_floors}F x {num_rooms}R x {num_addresses}A"
            total_addresses = num_floors * num_rooms * num_addresses
            
            print(f"\n{test_name} (Total: {total_addresses} addresses)")
            print("-" * 80)
            
            # Generate test data
            floors, all_addresses = self.generate_test_data(
                num_floors, num_rooms, num_addresses
            )
            
            # Benchmark legacy
            print("Running legacy implementation...")
            try:
                legacy_results = self.benchmark_legacy(floors, all_addresses)
                self.results['legacy'][test_name] = legacy_results
                self.print_results("Legacy", legacy_results)
            except Exception as e:
                print(f"Legacy failed: {e}")
                self.results['legacy'][test_name] = {'error': str(e)}
            
            # Benchmark refactored
            print("\nRunning refactored implementation...")
            try:
                refactored_results = self.benchmark_refactored(floors, all_addresses)
                self.results['refactored'][test_name] = refactored_results
                self.print_results("Refactored", refactored_results)
            except Exception as e:
                print(f"Refactored failed: {e}")
                self.results['refactored'][test_name] = {'error': str(e)}
            
            # Calculate comparison
            if 'error' not in self.results['legacy'].get(test_name, {}) and \
               'error' not in self.results['refactored'].get(test_name, {}):
                self.calculate_comparison(test_name)
        
        # Print summary
        self.print_summary()
    
    def print_results(self, name: str, results: Dict):
        """Print benchmark results."""
        print(f"{name} Results:")
        print(f"  Execution Time: {results['execution_time']:.4f}s")
        print(f"  Memory (Current): {results['memory_current_mb']:.2f} MB")
        print(f"  Memory (Peak): {results['memory_peak_mb']:.2f} MB")
        print(f"  Output Lines - Items: {results['items_lines']}, "
              f"Things: {results['things_lines']}, Sitemap: {results['sitemap_lines']}")
    
    def calculate_comparison(self, test_name: str):
        """Calculate performance comparison."""
        legacy = self.results['legacy'][test_name]
        refactored = self.results['refactored'][test_name]
        
        time_diff = ((legacy['execution_time'] - refactored['execution_time']) / 
                     legacy['execution_time'] * 100)
        mem_diff = ((legacy['memory_peak_mb'] - refactored['memory_peak_mb']) / 
                    legacy['memory_peak_mb'] * 100)
        
        self.results['comparison'][test_name] = {
            'time_improvement_percent': time_diff,
            'memory_improvement_percent': mem_diff
        }
        
        print(f"\nComparison:")
        print(f"  Time: {time_diff:+.1f}% ({'faster' if time_diff > 0 else 'slower'})")
        print(f"  Memory: {mem_diff:+.1f}% ({'less' if mem_diff > 0 else 'more'})")
    
    def print_summary(self):
        """Print benchmark summary."""
        print("\n" + "=" * 80)
        print("BENCHMARK SUMMARY")
        print("=" * 80)
        
        if self.results['comparison']:
            avg_time_improvement = sum(
                c['time_improvement_percent'] 
                for c in self.results['comparison'].values()
            ) / len(self.results['comparison'])
            
            avg_mem_improvement = sum(
                c['memory_improvement_percent'] 
                for c in self.results['comparison'].values()
            ) / len(self.results['comparison'])
            
            print(f"\nAverage Performance Improvement:")
            print(f"  Execution Time: {avg_time_improvement:+.1f}%")
            print(f"  Memory Usage: {avg_mem_improvement:+.1f}%")
        
        # Save results to file
        results_file = Path(__file__).parent / 'benchmark_results.json'
        with open(results_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"\nDetailed results saved to: {results_file}")


if __name__ == '__main__':
    benchmark = PerformanceBenchmark()
    benchmark.run_benchmark()
