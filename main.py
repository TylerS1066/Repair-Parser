import argparse
import collections
import gzip
import os
from dataclasses import dataclass
from datetime import datetime
import time
import logging
import yaml
import discord
from discord import app_commands



# Parse arguments
parser = argparse.ArgumentParser(description='Repair bot')
parser.add_argument('--log_directory', type=str, default='logs', help='Directory to store logs')
parser.add_argument('--token', type=str, help='Discord token')
parser.add_argument('--server_version', type=str, default='1.12.2', help='Server version')
args = parser.parse_args()



# Classes
class SplitError(ValueError):
    '''Represents an error splitting a line'''

class PricingError(ValueError):
    '''Represents an error pricing a line'''


@dataclass
class Repair:
    '''Represents a repair'''
    start: datetime
    damaged: int
    percent: float
    supplies: 'list[tuple[str, int]]'
    delay: int
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
        timestamp = datetime.strptime(timestamp, '%H:%M:%S')
        return timestamp.time()

    @staticmethod
    def __split_material_line(string: str) -> 'tuple[str, int]':
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
    def parse(lines: 'list[str]', start_index: int, end_index: int) -> 'Repair':
        '''Parses a repair from a list of lines'''
        damaged_index = start_index
        percentage_index = start_index + 1
        supply_start_index = start_index + 3
        supply_end_index = end_index - 2
        delay_index = end_index - 1
        cost_index = end_index


        # Reduce lines
        start = lines[start_index]
        start = Repair.__split_start_line(start)

        damaged = lines[damaged_index]
        damaged = Repair.__split_chat_line(damaged)
        damaged = Repair.__split_number_line(damaged)

        percent = lines[percentage_index]
        percent = Repair.__split_chat_line(percent)
        percent = Repair.__split_number_line(percent)

        supplies = []
        for index in range(supply_start_index, supply_end_index):
            line = lines[index]
            line = Repair.__split_chat_line(line)
            line = Repair.__split_material_line(line)
            supplies.append(line)

        delay = lines[delay_index]
        delay = Repair.__split_chat_line(delay)
        delay = Repair.__split_number_line(delay)

        cost = lines[cost_index]
        cost = Repair.__split_chat_line(cost)
        cost = Repair.__split_number_line(cost)

        # Attempt to find starting
        started = False
        for index in range(cost_index + 1, cost_index + 50):
            line = lines[index]
            try:
                line = Repair.__split_chat_line(line)
            except SplitError:
                continue
            if line.startswith('Repairs underway: 0/'):
                started = True
                break

        return Repair(start, damaged, percent, supplies, delay, cost, started)


    def total_cost(self, prices: dict[str, int]) -> float:
        '''Calculates the cost of a repair'''
        total = self.cost
        for supply, amount in self.supplies:
            if supply not in prices.keys():
                raise PricingError(f"{supply} is not in the prices dictionary")
            total += amount * prices[supply]
        return total

    def __str__(self):
        return f"{self.start}: {self.damaged:,} Blocks, ${self.cost:,.2f}, {self.delay:,.0f}s"



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


def log(interaction: discord.Interaction, attachment_name: str, filename: str,
        ending = 'No Errors'):
    '''Logs an interaction'''
    logger.info("'%s' (%s) uploaded '%s' (%s) to '%s'/'%s' (%s/%s): %s",
        interaction.user.name, interaction.user.id,
        attachment_name, filename,
        interaction.guild.name, interaction.channel.name,
        interaction.guild_id, interaction.channel_id,
        ending
    )

@tree.command()
@app_commands.describe(attachment='The log file to upload')
async def parse(interaction: discord.Interaction, attachment: discord.Attachment):
    '''Respond to an uploaded logfile'''
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
        filename = f"{datetime.utcnow().isoformat()}_{interaction.user.id}_{attachment.filename}"
        filename = os.path.join(args.log_directory, filename)
        if not os.path.exists(args.log_directory):
            os.mkdir(args.log_directory)
        await attachment.save(filename)
    except (discord.HTTPException, discord.NotFound) as exception:
        await interaction.followup.send(f"Error downloading attachment: {exception}")
        log(interaction, attachment.filename, filename, f"{exception}")
        return
    except BaseException as exception:
        await interaction.followup.send(f"Unknown error downloading: {exception}")
        log(interaction, attachment.filename, filename, f"{exception}")
        return

    # Attempt parsing
    try:
        repairs = parse_file(filename)
        results = collections.deque()
        results.append(f"{len(repairs)} repair{'' if len(repairs) == 1 else 's'} found")
        for repair in repairs:
            result = f"> {repair.start}: {repair.damaged:,} Blocks"
            try:
                result += f", ${repair.total_cost(material_costs):,.2f} & "
                result += f"{repair.delay:,.0f}s"
                if repair.started:
                    result += f" - Started for ${repair.cost:,.2f}"
            except PricingError as exception:
                result += f" & Error pricing: {exception}"
                logger.info('Error pricing: %s', exception)
            results.append(result)
    except SplitError as exception:
        await interaction.followup.send(f"{repair.start}: Error pricing - {exception}")
        log(interaction, attachment.filename, filename, f"{exception}")
        return
    except BaseException as exception:
        await interaction.followup.send(f"Unknown error parsing: {exception}")
        log(interaction, attachment.filename, filename, f"{exception}")
        return

    # Send results
    while len(results) > 0:
        message = ''
        while len(message) < 2000 and len(results) > 0 and len(message) + len(results[0]) < 2000:
            message += f"{results.popleft()}\n"
        await interaction.followup.send(message, ephemeral=True)
    log(interaction, attachment.filename, filename)


client.run(args.token)
