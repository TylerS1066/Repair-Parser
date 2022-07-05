import argparse
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
    supplies: 'list[tuple[str, int]]'
    cost: int
    delay: int


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
    def __split_delay_cost_line(string: str) -> int:
        strings = string.split(': ')
        if len(strings) < 2:
            raise SplitError(f"'{string}' cannot be split")
        if len(strings) > 2:
            raise SplitError(f"'{string}' was split too many times")
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
                raise PricingError(f"{supply} is not in the prices dictionary")
            total += amount * prices[supply]
        return total

    def __str__(self):
        return f"{self.start}: ${self.cost:,.2f} & {self.delay:,.0f}s"



# Utility functions
def parse_file(filename: str) -> list[Repair]:
    '''Parses a file and returns a list of repairs'''
    if filename.endswith('.gz'):
        with gzip.open(filename, 'rb') as file:
            log_lines = file.read().decode('UTF-8',errors='ignore').splitlines()
    else:
        with open(filename, 'rb') as file:
            log_lines = file.read().decode('UTF-8',errors='ignore').splitlines()

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
    with open(f"material_costs_{args.server_version}.yml", 'r', encoding='UTF-8') as f:
        costs = yaml.safe_load(f)
    return costs


# Discord.py stuff
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)

material_costs = load_materials()


@client.event
async def on_ready():
    '''Print when the bot is ready'''
    logger.info('Logged in as %s', client.user.name)


def log(interaction: discord.Interaction, attachment_name: str, filename: str, ending = 'No Errors'):
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
    # Check file name and size
    if not attachment.filename.endswith('.log.gz') and not attachment.filename.endswith('.log'):
        await interaction.response.send_message('File must be a .log.gz or .log file')
        log(interaction, attachment.filename, '', 'Wrong type')
        return
    if attachment.size > 32*1024*1024:
        await interaction.response.send_message('File must be less than 32MiB')
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
        result = f"{len(repairs)} repair{'' if len(repairs) == 1 else 's'} found\n"
        for repair in repairs:
            try:
                result += f"> {repair.start}: ${repair.total_cost(material_costs):,.2f} & "
                result += f"{repair.delay:,.0f}s\n"
            except PricingError as exception:
                result += f"> Error pricing: {exception}\n"
                log.info(f"Error pricing: {exception}")
    except SplitError as exception:
        await interaction.followup.send(f"{repair.start}: Error pricing - {exception}")
        log(interaction, attachment.filename, filename, f"{exception}")
        return
    except BaseException as exception:
        await interaction.followup.send(f"Unknown error parsing: {exception}")
        log(interaction, attachment.filename, filename, f"{exception}")
        return
    await interaction.followup.send(result, ephemeral=True)
    log(interaction, attachment.filename, filename)


client.run(args.token)
