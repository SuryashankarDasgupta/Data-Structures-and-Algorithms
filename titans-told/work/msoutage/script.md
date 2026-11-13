# Titans Told — 08: Microsoft outage
Working title A: Microsoft Outage: Why Outlook and Teams Went Down Worldwide
Tracker: 1 THE DAY IT BROKE (ACT 1) · 2 WHO WAS HIT (ACT 2) · 3 MICROSOFT'S STORY (ACT 3) · 4 THE SUSPECTS (ACT 4) · 5 THE OUTAGE ERA (ACT 5) · 6 WHY IT KEEPS HAPPENING (ACT 6)
Target: ~12 min, ~1,950 words

[[HOOK | 175 wpm | shock, tension, turn | <=21s]]
{steady} [tense] On Thursday, November twelfth, twenty twenty-six, Microsoft's email and work apps started failing around the world.

{fast} [urgent] Within an hour, Downdetector logged complaints from seventy-four countries and territories, and Outlook reports climbed to around one hundred and thirty thousand. [[beat]]

{steady} [intrigued] Yet Microsoft says it was not a cyberattack, and not a flood of traffic either. [serious] To understand what really broke, we have to look inside the servers.

[[QUESTION | 170 wpm | twist + open loop]]
{fast} [tense] And this is not even the first big Microsoft outage this year. It is part of a pattern that keeps knocking out the internet.

{slow} [curious] So how can one fault inside one company stop banks, courts and police on the other side of the planet, and why do these outages keep getting bigger?

[[ACT 1 | 165 wpm | the day it broke]]
{steady} [serious] Here is how the day unfolded, based on Microsoft's own status updates and reports from SecurityWeek, CIO and IBTimes. All times are in universal time.

{fast} [urgent] At sixteen seventeen, Microsoft opens an incident for Exchange Online, the system behind Outlook email. People cannot open their mailboxes on the web, in the desktop app or on their phones. Emails arrive late, or not at all.

{steady} [tense] At first, the problem looks local, with users in the Americas. Within about two hours, Microsoft warns that users in any region could be affected, and it opens a second, wider incident for everything that depends on Exchange.

{fast} [tense] Teams calendars stop loading. Copilot Chat stumbles. Even Defender, Microsoft's security service, cannot check some links in emails. Teams chat and meetings mostly keep working, but scheduling them does not.

{steady} [curious] By the evening, Microsoft pauses all software deployments and configuration changes. That is the corporate equivalent of everyone stepping away from the machine.

{steady} [hopeful] Then, a glimmer. Microsoft says it is returning a portion of the affected servers to service, and that they remain stable so far.

{slow} [ominous] But it does not last. Once those servers start receiving traffic again, many of them become unresponsive again. [[beat]] By Friday morning in London, the outage has run for more than twelve hours, and Microsoft still has no estimate for full recovery.

[[ACT 2 | 165 wpm | who was hit]]
{steady} [serious] So who actually felt it? Microsoft 365 has more than four hundred and fifty million paid commercial seats, according to IBTimes. Microsoft has not said how many of them were hit. But the stories tell you how deep it went.

{fast} [tense] In Australia, it is already Friday. Australia's spy agency, ASIO, and the Australian Federal Police are affected. Service NSW centres close in regional New South Wales, and the state's online bail court is disrupted, according to IBTimes.

{steady} [serious] Australia's Home Affairs Minister, Tony Burke, says Microsoft told the government, "They do not believe they are dealing with a cyber event." And Australia invokes a recovery-priority clause in an agreement it signed with Microsoft in June.

{fast} [urgent] In Hong Kong, bankers at Morgan Stanley and Goldman Sachs told CNN their work was disrupted. In New York, the city's emergency management office warns that email to city agencies could be delayed.

{steady} [knowing] And where there is chaos, there are scammers. ING Australia warns customers that criminals are exploiting the outage to send fake messages.

{steady} [curious] Even the AI companies notice. OpenAI and Anthropic report problems with the tools that connect their AI services to Microsoft three sixty-five, according to The Conversation.

{slow} [reflective] Picture what that means for a normal Thursday. A lawyer cannot send a filing. A teacher cannot reach remote students. A small business cannot see its orders. None of them did anything wrong. They simply ran on the same system.

[[ACT 3 | 160 wpm | microsoft's story]]
{steady} [curious] So what went wrong? Microsoft's explanation changed several times as the night went on, and that alone tells a story.

{steady} [serious] First, it pointed to elevated load across multiple regions. Then it corrected itself. The elevated load, it said, "isn't driven by an overall increase in traffic, but by a large number of servers being unexpectedly unavailable."

{slow} [knowing] Next, it narrowed it down. Servers were failing automated health checks, and "a process on the affected servers responsible for establishing secure connections becomes overwhelmed, causing the servers to stop processing requests."

{steady} [curious] Picture a hospital nurse who sends unwell patients home to rest. Big server fleets have a similar system, called health checks, that pulls sick machines out of service so they do not slow everyone else down.

{fast} [tense] But if the checker itself goes wrong, it starts sending healthy machines home too. Fewer servers means more work for the ones left. They get overwhelmed, fail their own checks, and get pulled out as well. Engineers call that a cascading failure.

{steady} [serious] Then came the twist. Microsoft had first said it found no recent change that matched the start of the problem. Overnight, according to SecurityWeek and CIO, it began reverting a recent network configuration change that coincided with the start of the disruption.

{steady} [skeptical] That is a lead, not a verdict. As of Friday, Microsoft had not confirmed a root cause, and SecurityWeek noted it had yet to explain why the health checks failed in the first place.

{slow} [serious] Microsoft executive vice president Charles Lamanna wrote on X, "We regret that today's outages caused disruptions for our customers." He added that there is "no indication this is the result of malicious or cyber activity."

[[SUBSCRIBE | 150 wpm | ~55% mark]]
{steady} [warm] Quick pause. If you want clear, fact-checked stories about how the giants of tech work, and how they break, subscribe to Titans Told. Now, back to the suspects.

[[ACT 4 | 160 wpm | the suspects]]
{steady} [curious] While Microsoft searched for answers, everyone else started guessing. Across forums, social media and newsrooms, the same suspects came up again and again.

{fast} [tense] Suspect number one was a cyberattack. When Outlook goes dark in seventy-four countries at once, many people assume someone did it on purpose. Outlets ran headlines asking exactly that.

{steady} [knowing] But the evidence points the other way. Microsoft, Australia's government and SecurityWeek all say there is no sign of malicious activity. And history backs them up. When Cloudflare went down in November twenty twenty-five, many first suspected an attack. It turned out to be a single oversized configuration file.

{steady} [curious] Suspect number two was Patch Tuesday. Just two days earlier, Microsoft had released its November security updates, fixing more than a thousand vulnerabilities, including an Outlook flaw that was already being exploited. SecurityWeek pointed out the timing, but Microsoft's advisories have not linked those updates to the outage.

{steady} [serious] Suspect number three was a bad change pushed to the network. This is the one Microsoft itself is now chasing, with the rollback of that network configuration change. It fits the pattern of most big outages, but until the post-incident report arrives, it is still a suspect, not a conviction.

{slow} [knowing] And suspect number four was the secure-connection system itself, the part of every server that sets up encrypted links. One independent test reported in the coverage found connections to Outlook opening, but the secure handshake never finishing. That matches what Microsoft described. It explains how the servers failed, but not yet why.

[[ACT 5 | 160 wpm | the outage era]]
{steady} [serious] Here is the bigger picture. This is not one bad day. It is part of an outage era.

{steady} [curious] Rewind to October twenty twenty-one. Facebook, Instagram and WhatsApp vanished for about six hours. A routine command during maintenance accidentally cut Facebook's data centres off from the rest of the internet, according to the company's own engineering report. Fixing it took extra time, the company said, because engineers had to get physical access to secure data centres to repair the network.

{fast} [tense] In July twenty twenty-four, a faulty CrowdStrike update crashed about eight and a half million Windows computers, by Microsoft's own estimate. Airports, hospitals and broadcasters went dark.

{steady} [knowing] In October twenty twenty-five, Amazon Web Services went down in its biggest region, in northern Virginia, for about fifteen hours. The cause was a hidden bug in the automation that manages DNS for one of its databases.

{steady} [serious] Just nine days later, Microsoft's own Azure Front Door, the gateway in front of many websites, failed worldwide for about eight hours after a configuration change produced data that crashed its servers.

{fast} [urgent] In November twenty twenty-five, Cloudflare stumbled when a database permissions change made one of its files double in size, and its software crashed across the network.

{steady} [serious] And in twenty twenty-six, Microsoft three sixty-five has already gone down in January, for hours, and in August, when a code update disrupted Outlook for days, according to The Conversation. Now November.

{slow} [reflective] Notice what these have in common. Almost none of them were attacks. They were changes, updates, files and automation that worked perfectly for years, until one day they did not.

[[ACT 6 | 160 wpm | why it keeps happening]]
{steady} [curious] So why do these outages keep getting bigger? There are three reasons.

{steady} [serious] The first is concentration. Just three companies, Amazon, Microsoft and Google, rent out most of the world's cloud computing. When one of them has a bad day, a huge share of the internet has one too.

{fast} [tense] The second is automation. Modern systems fix themselves faster than any human could. That is wonderful, until the automation makes the wrong call. Then it spreads the mistake faster than any human could, too.

{steady} [knowing] The third is that we stopped planning for failure. As analyst Sanchit Vir Gogia of Greyhound Research told CIO, "Enterprises have priced Microsoft 365 as a licence and never as a single point of failure."

{steady} [serious] His advice is simple. "The answer is not a second suite. It is a rehearsed fallback for the few things that cannot stop." That means a backup way to call your team, offline copies of critical files, and a plan that people have actually practised.

{steady} [knowing] And for everyday users, the advice from admins is just as simple. Mail is delayed, not lost, so do not resend everything. And do not trust that it is fixed until Microsoft's own status page says so.

{steady} [curious] And what do customers get back? Microsoft's business plans promise ninety-nine point nine percent monthly uptime, backed by service credits. That sounds close to perfect, but ninety-nine point nine percent still allows about forty-three minutes of downtime a month. This outage blew far past that.

{steady} [knowing] Even then, the credits are not automatic. According to admin guides like LazyAdmin, businesses have to file a claim through the Microsoft three sixty-five admin centre, citing the incident numbers. And a credit on next month's bill does not give anyone back a lost day of work.

{slow} [reflective] As Mahmoud Elkhodr of CQUniversity put it, "Outages of this scale are more often self-inflicted in this way than they are the work of attackers."

[[OUTRO | 150 wpm | reflection]]
{slow} [reflective] So the answer to our question is concentration, plus automation. The more of the world runs on a few companies' servers, and the more those servers run themselves, the further one small fault can travel.

{steady} [serious] Microsoft has promised a full post-incident report. When it arrives, we will know whether the suspect was the network change, the health checks, or something nobody has guessed yet.

{warm} If you want to see how another giant of tech was built, and how it almost fell, watch this one next. This has been Titans Told. See you in the next story.
