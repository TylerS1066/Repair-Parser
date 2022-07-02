from dataclasses import dataclass
from datetime import datetime
import time
import yaml



VERSION = '1.12.2'



@dataclass
class Repair:
    '''Represents a repair'''
    start: datetime
    supplies: 'list[tuple[str, int]]'
    cost: int
    delay: int


    @staticmethod
    def __split_chat_line(string: str, split: str = '[CHAT] ') -> str:
        string = string.strip()
        strings = string.split(split)
        if len(strings) < 2:
            raise ValueError(f"'{string}' cannot be split by '{split}'")
        if len(strings) > 2:
            raise ValueError(f"'{string}' was split by '{split}' too many times")
        return strings[1]

    @staticmethod
    def __split_start_line(string: str) -> time:
        timestamp = string.split('] ')[0][1:]
        timestamp = datetime.strptime(timestamp, '%H:%M:%S')
        return timestamp.time()

    @staticmethod
    def __split_material_line(string: str) -> 'tuple[str, int]':
        strings = string.split(' : ')
        if len(strings) < 2:
            raise ValueError(f"'{string}' cannot be split")
        if len(strings) > 2:
            raise ValueError(f"'{string}' was split too many times")
        return strings[0], int(strings[1])

    @staticmethod
    def __split_delay_cost_line(string: str) -> int:
        strings = string.split(': ')
        if len(strings) < 2:
            raise ValueError(f"'{string}' cannot be split")
        if len(strings) > 2:
            raise ValueError(f"'{string}' was split too many times")
        return int(strings[1])

    @staticmethod
    def parse(lines: 'list[str]', start_index: int, end_index: int) -> 'Repair':
        supply_start_index = start_index + 1
        cost_index = end_index
        delay_index = cost_index - 1
        supply_end_index = cost_index - 1

        # Reduce lines
        start = lines[start_index]
        start = Repair.__split_start_line(start)
        cost = lines[cost_index]
        cost = Repair.__split_chat_line(cost)
        cost = Repair.__split_delay_cost_line(cost)
        delay = lines[delay_index]
        delay = Repair.__split_chat_line(delay)
        delay = Repair.__split_delay_cost_line(delay)
        supplies = []
        for index in range(supply_start_index, supply_end_index):
            line = lines[index]
            line = Repair.__split_chat_line(line)
            line = Repair.__split_material_line(line)
            supplies.append(line)

        return Repair(start, supplies, cost, delay)


    def total_cost(self, prices: dict[str, int]) -> float:
        '''Calculates the cost of a repair'''
        total = self.cost
        for supply, amount in self.supplies:
            if supply not in prices.keys():
                raise ValueError(f"{supply} is not in the prices dictionary")
            total += amount * prices[supply]
        return total

    def __str__(self):
        return f"{self.start}: ${self.cost:,.2f} & {self.delay:,.0f}s"



def parse_file(filename: str) -> list[Repair]:
    '''Parses a file and returns a list of repairs'''
    with open(filename, 'r', encoding='UTF-8') as f:
        log_lines = f.readlines()

    repair_starts = []
    repair_ends = []
    i = 0
    for line in log_lines:
        if 'SUPPLIES NEEDED' in line:
            repair_starts.append(i)
        elif 'Money to complete repair: ' in line:
            repair_ends.append(i)
        i += 1

    repairs: list[Repair] = []
    for i in range(min(len(repair_starts), len(repair_ends))):
        repair = Repair.parse(log_lines, repair_starts[i], repair_ends[i])
        repairs.append(repair)
    return repairs

def load_materials() -> dict[str, int]:
    '''Loads the materials from the materials yaml file'''
    with open(f"material_costs_{VERSION}.yml", 'r', encoding='UTF-8') as f:
        material_costs = yaml.safe_load(f)
    return material_costs


if __name__ == '__main__':
    material_costs = load_materials()
    repairs = parse_file('latest.log')

    print(f"{len(repairs)} repair{'s' if len(repairs) > 1 else ''} found")
    for repair in repairs:
            print(f"{repair.start}: ${repair.total_cost(material_costs):,.2f} & {repair.delay:,.0f}s")