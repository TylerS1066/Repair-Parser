import argparse
import collections
import gzip
import json
import os
from dataclasses import dataclass
import datetime
import time
import logging
import yaml
import discord
from discord import app_commands



# Parse arguments
parser = argparse.ArgumentParser(description='Repair bot')
parser.add_argument('--log_directory', type=str, default='logs', help='Directory to store logs')
parser.add_argument('--token', type=str, help='Discord token')
parser.add_argument('--server_version', type=str, default='1.18.2', help='Server version')
args = parser.parse_args()



# Classes
class SplitError(ValueError):
    '''Represents an error splitting a line'''

class PricingError(ValueError):
    '''Represents an error pricing a line'''


@dataclass
class Repair:
    '''Represents a repair'''
    start_time: datetime.datetime
    block_count: int
    percent_damaged: float
    materials: dict[str, int]
    time_delay: int
    cost: int
    started: bool = False


    @staticmethod
    def __split_chat_line(string: str, split: str = '[CHAT] ') -> str:
        string = string.strip()
        strings = string.split(split)
        if len(strings) < 2:
            raise SplitError(f"'{string}' cannot be split by '{split}'")
        if len(strings) > 2:
            raise SplitError(f"'{string}' was split by '{split}' too many times")
        return strings[1]

    @staticmethod
    def __split_start_line(string: str) -> time:
        timestamp = string.split('] ')[0][1:]
        timestamp = datetime.datetime.strptime(timestamp, '%H:%M:%S')
        return timestamp.time()

    @staticmethod
    def __split_material_line(string: str) -> tuple[str, int]:
        strings = string.split(' : ')
        if len(strings) < 2:
            raise SplitError(f"'{string}' cannot be split")
        if len(strings) > 2:
            raise SplitError(f"'{string}' was split too many times")
        return strings[0], int(strings[1])

    @staticmethod
    def __split_number_line(string: str) -> int | float:
        strings = string.split(': ')
        if len(strings) < 2:
            raise SplitError(f"'{string}' cannot be split")
        if len(strings) > 2:
            raise SplitError(f"'{string}' was split too many times")
        try:
            return int(strings[1])
        except ValueError:
            return float(strings[1])

    @staticmethod
    def parse(lines: list[str], start_index: int, end_index: int) -> 'Repair':
        '''Parses a repair from a list of lines'''
        damaged_index = start_index
        percentage_index = start_index + 1
        supply_start_index = start_index + 3
        supply_end_index = end_index - 2
        delay_index = end_index - 1
        cost_index = end_index


        # Reduce lines
        start_time = lines[start_index]
        start_time = Repair.__split_start_line(start_time)

        block_count = lines[damaged_index]
        block_count = Repair.__split_chat_line(block_count)
        block_count = Repair.__split_number_line(block_count)

        percent_damaged = lines[percentage_index]
        percent_damaged = Repair.__split_chat_line(percent_damaged)
        percent_damaged = Repair.__split_number_line(percent_damaged)

        materials: dict[str, int] = {}
        for index in range(supply_start_index, supply_end_index):
            line = lines[index]
            line = Repair.__split_chat_line(line)
            line = Repair.__split_material_line(line)
            materials[line[0]] = line[1]

        time_delay = lines[delay_index]
        time_delay = Repair.__split_chat_line(time_delay)
        time_delay = Repair.__split_number_line(time_delay)

        cost = lines[cost_index]
        cost = Repair.__split_chat_line(cost)
        cost = Repair.__split_number_line(cost)

        # Attempt to find starting
        started = False
        for index in range(cost_index + 1, min(cost_index + 100, len(lines))):
            line = lines[index]
            try:
                line = Repair.__split_chat_line(line)
            except SplitError:
                continue
            if line.startswith('Repairs underway: 0/'):
                started = True
                break

        return Repair(start_time, block_count, percent_damaged, materials, time_delay, cost, started)


    def total_cost(self, prices: dict[str, int]) -> float:
        '''Calculates the cost of a repair'''
        total = self.cost
        for material, amount in self.materials.items():
            if material not in prices.keys():
                raise PricingError(f"{material} is not in the prices dictionary")
            total += amount * prices[material]
        return total

    def json(self) -> str:
        '''Generates a json summary of this repair'''
        return json.dumps({
            'start_time': self.start_time.isoformat(),
            'block_count': self.block_count,
            'percent_damaged': self.percent_damaged,
            'materials': self.materials,
            'time_delay': self.time_delay,
            'cost': self.cost,
            'started': self.started
        })

    def __str__(self):
        return f"{self.start_time}: {self.block_count:,} Blocks, ${self.cost:,.2f}, {self.time_delay:,.0f}s"



# Utility functions
def parse_file(filename: str) -> list[Repair]:
    '''Parses a file and returns a list of repairs'''
    if filename.endswith('.gz'):
        with gzip.open(filename, 'rb') as file:
            log_lines = file.read().decode('UTF-8',errors='ignore').splitlines()
    else:
        with open(filename, 'rb') as file:
            log_lines = file.read().decode('UTF-8',errors='ignore').splitlines()

    repair_bounds = []
    start = -1
    end = -1
    i = 0
    for line in log_lines:
        if 'Total damaged blocks: ' in line:
            start = i
        elif 'Money to complete repair: ' in line:
            end = i
            if start != -1:
                repair_bounds.append((start, end))
        i += 1

    repairs: list[Repair] = []
    for start, end in repair_bounds:
        repair = Repair.parse(log_lines, start, end)
        repairs.append(repair)
    return repairs

def load_materials() -> dict[str, int]:
    '''Loads the materials from the materials yaml file'''
    with open(f"material_costs_{args.server_version}.yml", 'r', encoding='UTF-8') as file:
        costs = yaml.safe_load(file)
    return costs

def load_guilds() -> list[int]:
    '''Loads the guilds from the guilds yaml file'''
    with open('guilds.yml', 'r', encoding='UTF-8') as file:
        guilds = yaml.safe_load(file)
    return guilds['guilds']

# Discord.py stuff
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)

material_costs = load_materials()
allowed_guilds = load_guilds()


@client.event
async def on_ready():
    '''Print when the bot is ready'''
    logger.info('Logged in as %s', client.user.name)
    await tree.sync()
    logger.info('Synced commands')


def log(interaction: discord.Interaction, attachment_name: str, filename: str,
        ending = 'No Errors'):
    '''Logs an interaction'''
    channel_name = ''
    try:
        channel_name = interaction.channel.name
    except BaseException as e:
        channel_name = 'null'

    logger.info(f"'{interaction.user.name}' ({interaction.user.id}) uploaded '{attachment_name}' ({filename}) to '{interaction.guild.name}'/'{channel_name}' ({interaction.guild_id}/{interaction.channel_id}): {ending}")

def __format_delay(delay: int) -> str:
    '''Nicely formats a time delay'''
    seconds = delay

    minutes = delay // 60
    seconds %= 60
    hours = minutes // 60
    minutes %= 60
    days = hours // 24
    hours %= 24

    result = ''
    if days > 0:
        result += f"{days:,.0f}d "
    if hours > 0:
        result += f"{hours:,.0f}h "
    if minutes > 0:
        result += f"{minutes:,.0f}m "
    if seconds > 0:
        result += f"{seconds:,.0f}s "
    result += f"({delay:,.0f}s)"
    return result

@tree.command(name='parse')
@app_commands.describe(attachment='The log file to upload')
async def parse_summary(interaction: discord.Interaction, attachment: discord.Attachment):
    '''Respond to an uploaded logfile with a summary'''
    # Check allowed guilds
    if interaction.guild_id not in allowed_guilds:
        await interaction.response.send_message("This server is not allowed to use this bot")
        return
    # Check file name and size
    if not attachment.filename.endswith('.log.gz') and not attachment.filename.endswith('.log'):
        await interaction.response.send_message('File must be a .log.gz or .log file',
            ephemeral=True)
        log(interaction, attachment.filename, '', 'Wrong type')
        return
    if attachment.size > 32*1024*1024:
        await interaction.response.send_message('File must be less than 32MiB', ephemeral=True)
        log(interaction, attachment.filename, '', f"Too large ({attachment.size:,} bytes)")
        return

    # Defer response
    await interaction.response.defer(ephemeral=True, thinking=True)

    # Attempt to download
    try:
        filename = f"{datetime.datetime.now(datetime.UTC).isoformat()}_{interaction.user.id}_{attachment.filename}".replace(':', '-')
        filename = os.path.join(args.log_directory, filename)
        if not os.path.exists(args.log_directory):
            os.mkdir(args.log_directory)
        await attachment.save(filename)
    except (discord.HTTPException, discord.NotFound) as exception:
        await interaction.followup.send(f"Error downloading attachment: {exception}",
            ephemeral=True)
        log(interaction, attachment.filename, filename, f"{exception}")
        return
    except BaseException as exception:
        await interaction.followup.send(f"Unknown error downloading: {exception}", ephemeral=True)
        log(interaction, attachment.filename, filename, f"{exception}")
        return

    # Attempt parsing
    try:
        repairs = parse_file(filename)
    except SplitError as exception:
        await interaction.followup.send(f"Error pricing - {exception}", ephemeral=True)
        log(interaction, attachment.filename, filename, f"{exception}")
        return
    except BaseException as exception:
        await interaction.followup.send(f"Unknown error parsing: {exception}", ephemeral=True)
        log(interaction, attachment.filename, filename, f"{exception}")
        return

    # Attempt summarizing
    try:
        results = collections.deque()
        results.append(f"{len(repairs)} repair{'' if len(repairs) == 1 else 's'} found")
        for repair in repairs:
            result = f"> {repair.start_time}: {repair.block_count:,} Blocks"
            try:
                result += f", ${repair.total_cost(material_costs):,.2f} & "
                result += __format_delay(repair.time_delay)
                if repair.started:
                    result += f" - Started for ${repair.cost:,.2f}"
            except PricingError as exception:
                result += f" & Error pricing: {exception}"
                logger.info('Error pricing: %s', exception)
            results.append(result)
    except BaseException as exception:
        await interaction.followup.send(f"Unknown error summarizing: {exception}", ephemeral=True)
        log(interaction, attachment.filename, filename, f"{exception}")
        return

    # Send results
    while len(results) > 0:
        message = ''
        while len(message) < 2000 and len(results) > 0 and len(message) + len(results[0]) < 2000:
            message += f"{results.popleft()}\n"
        await interaction.followup.send(message, ephemeral=True)
    log(interaction, attachment.filename, filename)


@tree.command(name='parse-json')
@app_commands.describe(attachment='The log file to upload')
async def parse_json(interaction: discord.Interaction, attachment: discord.Attachment):
    '''Respond to an uploaded logfile with JSON'''
    # Check allowed guilds
    if interaction.guild_id not in allowed_guilds:
        await interaction.response.send_message("This server is not allowed to use this bot")
        return
    # Check file name and size
    if not attachment.filename.endswith('.log.gz') and not attachment.filename.endswith('.log'):
        await interaction.response.send_message('File must be a .log.gz or .log file',
            ephemeral=True)
        log(interaction, attachment.filename, '', 'Wrong type')
        return
    if attachment.size > 32*1024*1024:
        await interaction.response.send_message('File must be less than 32MiB', ephemeral=True)
        log(interaction, attachment.filename, '', f"Too large ({attachment.size:,} bytes)")
        return

    # Defer response
    await interaction.response.defer(ephemeral=True, thinking=True)

    # Attempt to download
    try:
        filename = f"{datetime.datetime.now(datetime.UTC).isoformat()}_{interaction.user.id}_{attachment.filename}".replace(':', '-')
        filename = os.path.join(args.log_directory, filename)
        if not os.path.exists(args.log_directory):
            os.mkdir(args.log_directory)
        await attachment.save(filename)
    except (discord.HTTPException, discord.NotFound) as exception:
        await interaction.followup.send(f"Error downloading attachment: {exception}",
            ephemeral=True)
        log(interaction, attachment.filename, filename, f"{exception}")
        return
    except BaseException as exception:
        await interaction.followup.send(f"Unknown error downloading: {exception}", ephemeral=True)
        log(interaction, attachment.filename, filename, f"{exception}")
        return

    # Attempt parsing
    try:
        repairs = parse_file(filename)
    except SplitError as exception:
        await interaction.followup.send(f"Error pricing - {exception}", ephemeral=True)
        log(interaction, attachment.filename, filename, f"{exception}")
        return
    except BaseException as exception:
        await interaction.followup.send(f"Unknown error parsing: {exception}", ephemeral=True)
        log(interaction, attachment.filename, filename, f"{exception}")
        return

    # Attempt detailing
    results = collections.deque()
    results.append(f"{len(repairs)} repair{'' if len(repairs) == 1 else 's'} found")
    for repair in repairs:
        results.append(f"```json\n{repair.json()}\n```\n")

    # Send results
    while len(results) > 0:
        message = ''
        while len(message) < 2000 and len(results) > 0 and len(message) + len(results[0]) < 2000:
            message += f"{results.popleft()}\n"
        await interaction.followup.send(message, ephemeral=True)
    log(interaction, attachment.filename, filename)

client.run(args.token)
