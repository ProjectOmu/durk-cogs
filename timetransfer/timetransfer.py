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

class TimeTransfer(commands.Cog):
    def __init__(self, bot):
            self.bot = bot
    ttransfer = app_commands.Group(name="timetransfer", description="TimeTransfer related commands")
    
    @ttransfer.command(name="format", description="Sends the format used for time transfers")
    async def ttransfer_format(self, interaction: discord.Interaction):
        ss14output = "```\nUsername=YOUR_SS14_USERNAME"
        channel = interaction.channel
        for x in FormatJobs:
            ss14output = ss14output + "\n" + x + "=MINUTES"
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
        textin = textin.replace(" ","")
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
                ss14splitline  = line.split(sep="=")
                ss14job = ss14splitline[0]
                if ss14job in ValidJobs:
                    ss14minutes = ss14splitline[1]
                    ss14command = f"playtime_addrole {ss14username} {ss14job} {ss14minutes}"
                    ss14output = ss14output + "\n" + ss14command
                else: 
                    ss14output = f"Invalid job entered `{ss14job}`"
                    break
    
        await channel.send(f"```\n{ss14output}\n```")
        print("timetransfer complete.")
