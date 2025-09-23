import discord

from redbot.core import commands, app_commands
import re

FormatJobs = [
    "JobAtmosphericTechnician",
    "JobBartender",
    "JobBlueshieldOfficer",
    "JobBorg",
    "JobBotanist",
    "JobBoxer",
    "JobBrigmedic",
    "JobCaptain",
    "JobCargoTechnician",
    "JobChaplain",
    "JobChef",
    "JobChemist",
    "JobChiefEngineer",
    "JobChiefMedicalOfficer",
    "JobClown",
    "JobDetective",
    "JobHeadOfPersonnel",
    "JobHeadOfSecurity",
    "JobJanitor",
    "JobLawyer",
    "JobLibrarian",
    "JobMedicalDoctor",
    "JobMedicalIntern",
    "JobMime",
    "JobMusician",
    "JobNanotrasenRepresentative",
    "JobParamedic",
    "JobPassenger",
    "JobPsychologist",
    "JobQuartermaster",
    "JobReporter",
    "JobResearchAssistant",
    "JobResearchDirector",
    "JobSalvageSpecialist",
    "JobScientist",
    "JobSecurityCadet",
    "JobSecurityOfficer",
    "JobServiceWorker",
    "JobStationAi",
    "JobStationEngineer",
    "JobTechnicalAssistant",
    "JobVisitor",
    "JobWarden",
    "JobZookeeper"
]

ValidJobs = [
    "JobAtmosphericTechnician",
    "JobBartender",
    "JobBlueshieldOfficer",
    "JobBorg",
    "JobBotanist",
    "JobBoxer",
    "JobBrigmedic",
    "JobCaptain",
    "JobCargoTechnician",
    "JobCBURN",
    "JobCentCommDireggtor",
    "JobCentCommIntern",
    "JobCentralCommandOfficial",
    "JobChaplain",
    "JobChef",
    "JobChemist",
    "JobChiefEngineer",
    "JobChiefMedicalOfficer",
    "JobClown",
    "JobConquest",
    "JobDeathSquad",
    "JobDetective",
    "JobDiplomat",
    "JobERTChaplain",
    "JobERTEngineer",
    "JobERTJanitor",
    "JobERTLeader",
    "JobERTMedical",
    "JobERTSecurity",
    "JobGovernmentMan",
    "JobHeadOfPersonnel",
    "JobHeadOfSecurity",
    "JobHecuOperative",
    "JobHighCommander",
    "JobInspector",
    "JobJanitor",
    "JobLawyer",
    "JobLibrarian",
    "JobMedicalDoctor",
    "JobMedicalIntern",
    "JobMercenaryCaptain",
    "JobMime",
    "JobMusician",
    "JobNanotrasenCareerTrainer",
    "JobNanotrasenRepresentative",
    "JobNavyCaptain",
    "JobNavyOfficer",
    "JobNavyOfficerUndercover",
    "JobParamedic",
    "JobPassenger",
    "JobPsychologist",
    "JobQuartermaster",
    "JobReporter",
    "JobResearchAssistant",
    "JobResearchDirector",
    "JobSalvageSpecialist",
    "JobScientist",
    "JobSecurityCadet",
    "JobSecurityOfficer",
    "JobServiceWorker",
    "JobSpecialOperationsOfficer",
    "JobStationAi",
    "JobStationEngineer",
    "JobTechnicalAssistant",
    "JobVisitor",
    "JobWarden",
    "JobZookeeper"
]


def converttime(data: str):  # Takes in data in the format "HOURS|MINUTES"
    splitdata = data.split("|")
    hours = splitdata[0]
    hours = re.sub("[^0-9]", "", hours)
    hours = int(hours)
    minutes = splitdata[1]
    minutes = re.sub("[^0-9]", "", minutes)
    minutes = int(minutes)
    totaltime = ((hours*60)+minutes)
    return totaltime


class TimeTransfer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    ttransfer = app_commands.Group(
        name="timetransfer", description="TimeTransfer related commands")

    @ttransfer.command(name="format", description="Sends the format used for time transfers")
    async def ttransfer_format(self, interaction: discord.Interaction):
        ss14output = "```\nUsername=YOUR_SS14_USERNAME"
        channel = interaction.channel
        for x in FormatJobs:
            if len(ss14output + "\n" + x + "=HOURS|MINUTES") < 1900:
                ss14output = ss14output + "\n" + x + "=HOURS|MINUTES"
            else:
                ss14output = ss14output + "\n```"
                await channel.send(ss14output)
                ss14output = "```\nUsername=YOUR_SS14_USERNAME"
                ss14output = ss14output + "\n" + x + "=HOURS|MINUTES"
        ss14output = ss14output + "\n```"
        await interaction.response.send_message(ss14output)

    @ttransfer.command(name="create", description="Creates a time transfer")
    async def ttransfer_create(self, interaction: discord.Interaction, timetransfer_message_id: str):
        timetransfer_message_id = int(timetransfer_message_id)
        await interaction.response.send_message("Creating time transfer command.")
        guild = interaction.guild
        channel = interaction.channel
        msg = await channel.fetch_message(timetransfer_message_id)
        textin = msg.content
        textin = textin.replace(" ", "")
        textin = textin.replace("`", "")
        textlines = textin.splitlines()
        ss14output = ""
        isfirstline = True
        ss14username = ""
        for line in textlines:
            if isfirstline == True:
                ss14splitline = line.split(sep="=")
                ss14username = ss14splitline[1]
                isfirstline = False
            else:
                ss14splitline = line.split(sep="=")
                ss14job = ss14splitline[0]
                if ss14job in ValidJobs:
                    ss14timedata = ss14splitline[1]
                    if ss14timedata != "HOURS|MINUTES":
                        ss14minutes = converttime(ss14timedata)
                        if ss14minutes != 0:
                            ss14command = f"playtime_addrole {ss14username} {ss14job} {ss14minutes}"
                            if len(ss14output+"\n"+ss14command) < 1900:
                                ss14output = ss14output + "\n" + ss14command
                            else:
                                await channel.send(f"```\n{ss14output}\n```")
                                ss14output = ""
                                ss14output = ss14output + "\n" + ss14command
                else:
                    ss14output = f"Invalid job entered `{ss14job}`"
                    break
        await channel.send(f"```\n{ss14output}\n```")
        print("timetransfer complete.")
