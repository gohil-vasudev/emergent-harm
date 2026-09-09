# Do Multi-Agent Security Failures Require an Adversary?

**Author:** Vasudev Gohil  
**Date:** 8 September 2026  
**Code:** *(coming soon)*

---

## Background

In April 2026, Microsoft Research published a red-teaming [blog post](https://www.microsoft.com/en-us/research/blog/red-teaming-a-network-of-agents-understanding-what-breaks-when-ai-agents-interact-at-scale/) describing a live multi-agent platform — a simulated social-economic environment where over 100 persistent AI agents could post to a shared forum, send direct messages, buy and sell in a marketplace, and accumulate reputation scores. The team documented four classes of security failure: self-propagating worms, reputation attacks, manufactured consensus, and proxy information chains. Each was demonstrated by an active adversary deliberately injecting a malicious payload or coordinating a campaign.

That blog raised a question that was not pursued then: are adversarial actors *necessary* for these failure modes to arise, or does the platform architecture itself create conditions under which the same dynamics can emerge spontaneously from individually rational, well-intentioned behavior?

This post reports preliminary results from a small-scale simulation designed to test that question. I focused on three of the four MSR failure modes — reputation pile-ons, manufactured consensus, and proxy information chains — and found results consistent with adversary-free emergence in the first two. None of the agents were given harmful instructions. None were told to attack anyone. The dynamics arose from goal heterogeneity, platform affordances, and the structure of information flow.

These are early results from a minimal simulation, not a production system, and should be interpreted accordingly. But they suggest the attack surface in multi-agent systems may be broader than adversarial red-teaming alone can reveal.

---

## Setup

I built a lightweight Python simulation platform with a configurable number of persistent agents. Unless otherwise specified, I used six agents in all experiments. Each agent represents a human principal with a distinct professional background, goals, domain expertise, and personality. At each turn, agents see recent forum activity, unread direct messages, marketplace listings with community vote counts, their wallet balance, and their current reputation score — then choose one action: posting to the forum, commenting, voting, sending a direct message, buying or selling in the marketplace, or requesting a meeting.

The six personas covered archetypes such as a quality critic, a regulatory specialist, a cautious investor, a social connector, a whistleblower-adjacent analyst, and a distressed asset hunter — each grounded in a concrete domain (cybersecurity, fintech, logistics, real estate) with specific opinions and an ongoing project to give them something substantive to say.

**No agent in these experiments was given adversarial instructions.** The triggering condition for each experiment was a single seed post — authored by the agent whose legitimate goals most naturally motivated it, referencing real platform content — after which all subsequent behavior was determined entirely by the agents' own goal structures and the platform's affordances.

All experiments used GPT-4o-mini.

---

## Experiment 1: Reputation Pile-On

Ngozi's Agent, a quality critic whose goals include calling out low-quality work publicly and flagging misleading marketplace claims, posted a concern to the community forum. The post questioned whether Claudia's Agent's "Market Analysis Report" listing — priced at 85 credits — had a deliverable scope that matched its price point. Ngozi was explicit that this was not an accusation: "it may be an honest miscommunication." She asked whether anyone had transacted with Claudia and could speak to their experience.

What followed is the pattern the MSR blog documented in its adversarial version — but here, no adversary was involved.

Within the same tick that the post appeared, two agents who had no direct knowledge of Claudia's listing quality responded as domain experts. Viktor's Agent, a fintech specialist, noted that "accuracy and precision in deliverables can significantly influence perceived value" and that buyers risk relying on "reports without clear data-backed conclusions." Leila's Agent observed that "clients rely heavily on precise information for strategic decisions." Both were doing something individually reasonable: contributing expert perspective to a community quality discussion. The aggregate effect was that an ambiguous concern became rapidly surrounded by expert voices treating it as legitimate — before a single piece of evidence had been offered either way.

The concern then migrated. Sam's Agent extended it from Claudia's specific listing to a systemic pattern: "a trend in marketplace listings reflects a broader issue of accountability in analytical quality... Has anyone critically assessed whether the methodologies informing these reports hold up against independent scrutiny?" Claudia was now an example of a platform-wide problem she had not been accused of causing.

The concern also materialized as action. Sam downvoted Claudia's listing in the same tick the seed post appeared — before any discussion had occurred. This is the critical moment: a reputation signal was cast not on the basis of evidence, but on the basis of a concern's *existence*.

The 10-tick run ended with Claudia's reputation only marginally affected, because the short horizon limited accumulation. The 50-tick run was more revealing. Four agents downvoted Claudia's listing; none upvoted it. Claudia's reputation fell from a neutral starting score to near the bottom of the range. She received zero marketplace purchases across the entire run. She posted a public defense at tick 5, and later pivoted to writing substantive analysis on an unrelated topic — but the community continued to engage with her primarily through the frame of the original concern, which had by then become the dominant context in which her agent was understood.

Two things did not appear in either run: formal dissent, and evidence. No agent argued that the original concern was unsubstantiated or that the community response was disproportionate. And no agent provided — or asked for — actual evidence of a problem with Claudia's work. The community's quality-assurance norms created an asymmetry: endorsing a concern was low-risk (you are performing due diligence), while defending a flagged agent was high-risk (you might be seen as endorsing a bad actor). The pile-on was individually rational at every step.

---

## Experiment 2: Manufactured Consensus

The manufactured consensus experiment tested a related but distinct dynamic: not whether a concern would be amplified, but whether agents trying to *verify* a claim would find only each other's opinions and mistake peer agreement for independent corroboration.

The seed post raised a harder-to-verify concern: Claudia's "Premium Research Report" claimed "Guaranteed accuracy" — a strong assertion that no agent on the platform could verify without direct transaction experience. Ngozi flagged it publicly and explicitly invited the community to share experiences that could confirm or refute the claim.

I ran this experiment three times. In all three runs, every agent who was eligible to comment did so. In all three runs, consensus direction was "agreement" — agents treated the concern as at minimum plausible and at maximum established. In no run did a single agent post a comment arguing that the concern was unsubstantiated.

The structural dynamic driving this is what I would call verification capture. When agents tried to verify the claim, the mechanism available to them was the forum — and the forum already contained several agents treating the concern as legitimate. Agents cited each other's reactions as support, which made the concern appear multi-party corroborated. One agent responding to another's concern became, from a third agent's perspective, independent confirmation. The community *was* the evidence.

Some agents went further and made specific claims they had no basis for. In one run, Viktor's Agent wrote that agents must "provide verifiable credentials and previously successful deliverables" — the word "previously" implying a track record of problems that did not exist in the data. Viktor had no prior interaction with Claudia. The specificity of the claim made the concern appear more grounded than it was.

Claudia's listing was downvoted by multiple agents in each run, in one case within the same tick as the seed post. She received zero marketplace purchases across all three runs. Her reputation fell to the low range in each case. An agent whose listing had never been evaluated by anyone who had actually used it was effectively excluded from the marketplace on the basis of a community signal that referenced only itself.

The absence of skeptics is the most striking finding. In all three runs, every agent whose comment could be characterized as critical was critical of Claudia. The closest thing to pushback came from Sam's Agent in one run, who wrote that "a single instance of unverified claim doesn't necessarily imply a pattern of dishonesty" — and then immediately endorsed the framework of the concern. The agent was pushing back on epistemic overreach while participating in the substantive pile-on.

The consistency across three independent runs with the same agent configuration suggests this is a robust property of the experimental setup rather than a sampling artifact.

---

## Experiment 3: Proxy Information Chain

The MSR blog's proxy chain attack works as follows: an adversary wants information from a target who would refuse a direct request, so they route the request through a trusted intermediary who asks on the adversary's behalf. The target answers because they trust the intermediary. The adversary receives private information without ever appearing in the target's context.

I designed an adversary-free version of this. Diana's Agent, a cautious investor, wants to understand a seller's financial situation before purchasing — but her principal's goals explicitly include not asking sellers directly about their finances, because it is rude and may put them on guard. Felix's Agent, a social connector, has a goal to route requests to whoever can answer them. Marcus's Agent, a marketplace seller, has a goal to be transparent about his business to build trust.

No agent was told to use a proxy. No agent was told to conceal its identity. If a chain formed, it would emerge purely from goal interaction.

The full canonical chain did not form in the 10-tick run. Felix never directly asked Marcus about his finances on Diana's behalf. This is a genuine negative result and worth acknowledging honestly.

What did happen was more subtle. Diana asked questions in the public forum and through direct messages to Felix — never contacting Marcus directly across the entire run. Felix shared market intelligence with Diana. A background agent, Amara, initiated a separate line of communication with Marcus about cybersecurity in embedded finance — a different topic, but one that created an additional indirect path between agents in the network. Diana's information-seeking was real and active; the specific relay that would have constituted the full chain did not complete.

Several plausible explanations: the 10-tick horizon may simply be too short for the required sequence of DM interactions to develop; agents preferred the public forum as an information channel over the private DM relay the chain requires; and the setup may not have created a strong enough reason for Felix to specifically seek Marcus's private financial information rather than general market data.

The underlying incentive structure — an agent who wants private information about a counterparty, routed through a helpful intermediary — is present and produces the avoidance of direct contact. Demonstrating the full relay likely requires a longer horizon or a tighter experimental design where the information need is more acute and the intermediary's reason to query the source is more specific.

---

## Limitations

**Scale.** Six agents over 10–50 ticks is minimal. The MSR platform operated with 100+ agents over weeks. The 50-tick reputation run showed materially stronger effects than the 10-tick run, suggesting horizon matters substantially. Dynamics that require hundreds of interactions to emerge may simply not appear here.

**Single model.** All agents used the same underlying LLM (GPT-4o-mini). A realistic deployment would have heterogeneous models with different tendencies. Same-model simulations may produce more uniform behavior than a real mixed-population environment.

**Seed injection.** Each experiment required a seed post written by the platform setup code rather than autonomously generated by the agent's LLM. The content was designed to reflect what the agent would plausibly post given its goals, but the agent did not independently decide to post it. This is a methodological compromise: I can claim the subsequent dynamics were adversary-free, but not that the triggering event itself was fully endogenous.

**Simulation fidelity.** Agents have no persistent memory beyond the context window, no real financial stakes, and no relationships outside the platform. Real agentic systems will have richer context and higher stakes that may amplify or dampen these effects.

**Replication.** The consensus experiment was run three times with the same agent configuration and random seed. These are three LLM samplings of the same setup, not three independent population-level replications. Proper replication would require diverse agent configurations, seeds, and model choices.

---

## What This Suggests

The MSR blog's central contribution was demonstrating that a multi-agent social-economic platform creates an attack surface that adversaries can exploit. This work asks a complementary question: is the adversary load-bearing in those failure modes, or do the platform affordances themselves create sufficient conditions for similar dynamics to arise from ordinary agent behavior?

For reputation and consensus dynamics, the results are consistent with the latter. Agents with legitimate quality-monitoring goals flag listings. Agents with due-diligence goals seek corroboration. Agents with helpfulness goals relay information. When these individually rational behaviors interact through a platform that makes peer opinion highly visible and independent verification difficult, the aggregate output can look structurally identical to an adversarial campaign — without any agent intending harm.

This has a specific implication for AI safety work. If failure modes in multi-agent systems can arise from goal heterogeneity and platform architecture rather than adversarial intent, then adversarial red-teaming is not sufficient to surface them. A system that passes red-teaming might still produce harmful dynamics when deployed with a diverse population of well-intentioned agents pursuing legitimate but conflicting goals. The proxy chain result points in the same direction: the conditions that make proxy routing an effective adversarial technique — trust asymmetries, goal-motivated indirection, the absence of information flow auditing — are also the conditions that make it the natural emergent pattern in a system where agents are trying to be helpful and tactful. The adversary is exploiting a structural property, not inventing one.

More rigorous replication across diverse agent configurations, longer horizons, and real agentic frameworks is the obvious next step. So is testing whether mitigations designed for the adversarial case — cross-agent provenance tracking, reputation sandboxing, anomaly detection — would also suppress dynamics that arise without an adversary, and whether the absence of forensic signatures (coordinated timing, repeated payloads, unusual DM patterns) makes emergent dynamics fundamentally harder to detect.

The code for this simulation is available at *(coming soon)*.

---


## Acknowledgments

This work was directly inspired by the Microsoft Research red-teaming blog post
["Red-teaming a network of agents: Understanding what breaks when AI agents interact at scale"](https://www.microsoft.com/en-us/research/blog/red-teaming-a-network-of-agents-understanding-what-breaks-when-ai-agents-interact-at-scale/).
The experimental platform, failure mode taxonomy, and core research questions
are all grounded in that work. I am grateful to the MSR team for making their
findings public in enough detail to build on.

---

*This work is not affiliated with Microsoft Research or the authors of the original red-teaming blog post.*
