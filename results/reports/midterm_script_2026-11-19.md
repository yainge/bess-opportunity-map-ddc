# Mid-term presentation script (19 Nov 2026)

Deck: https://claude.ai/artifact/HWh7VR8j1CZRAYQnRESC8U

Total: 1626 words, about 12 minutes at a steady pace.

## 1. Where should grid-scale batteries go in Catalonia?

Good morning. We are building a screening map that helps a battery developer decide where in Catalonia to look first.

In October we showed you a ranked list of substations. Today we will show you what that ranking looks like on real data, why we no longer think a ranking alone is enough, and the clustering experiment we ran to answer the feedback we got two weeks ago.

We will finish with what is still missing and our plan to the final in December.

_84 words, about 35 seconds_

## 2. A developer has to pick a place before they can study it

Our user is a battery developer or investor. Before they pay for a detailed connection study, they need to decide which part of Catalonia is worth studying at all.

Today that first decision means pulling together grid capacity from the transmission operator, demand by municipality, the renewable project register and land-use rules. These are separate sources in separate formats.

Our tool puts them in one reproducible pipeline and produces a map. We want to be clear about what it is: a first filter. It tells you where to look first and gives the reasons. It does not tell you that a site is buildable or that a connection is available.

_110 words, about 45 seconds_

## 3. What changed since October, and why

In October our concept was a multi-criteria ranking. Every substation gets a score on several indicators, we apply weights, and we sort the list.

Two things changed our mind. First, the weights were our own guess, and we could not defend them as data-driven. Second, in the session on the fifth of November, Ferran pointed out that two places can be close on the map and still not be connected electrically, so geography alone is not enough.

So the updated concept is this. We keep the ranking as a transparent baseline, because it is easy to explain. Next to it, we let a clustering algorithm form regions from the data: groups of nodes that look alike and that are connected. Then we describe what makes each region different.

_128 words, about 55 seconds_

## 4. Four of five datasets are real and in the pipeline

Here is what we have. Four of our five planned datasets are real and run through the pipeline from raw file to map.

We have 117 transmission nodes at 220 and 400 kilovolts, each with its published access capacity. We have electricity demand for all 947 municipalities in Catalonia. We have 610 renewable installations, of which 120 are operating and the rest are in the pipeline. And we have six map layers that tell us where land is suitable or excluded.

The fifth dataset is congestion, and that number is zero. We have not found a usable source for congestion or curtailment at node level. We come back to that at the end, because it affects what we can claim.

_120 words, about 50 seconds_

## 5. The ranking works, but it rests on our weights

This is the baseline: every node scored and coloured, here for the connection-readiness scenario. Green is better. The hatched areas are hard constraints such as protected land.

We score three scenarios: renewable absorption, connection readiness, and load support. Each gives a different top ten. For connection readiness, Ascó, Vic and La Secuita come out on top.

We tested how much to trust this. When we move every weight up or down by twenty percent, five hundred times, the top ten barely moves. That is reassuring. But when we remove one indicator completely, the top ten can change a lot. So the ranking is stable to small changes in the weights and fragile to the choice of indicators.

Also, 34 of the 117 nodes get no rank, because a hard constraint excludes them or data is missing. This is what pushed us to look for a method that depends less on our own weights.

_153 words, about 65 seconds_

## 6. Same nodes, same features, same method. Only one thing changes: which nodes are allowed to merge.

So we ran an experiment. We took the same 117 nodes and described each with seven features: grid headroom, operating renewables nearby, renewables in the pipeline, total demand, industrial demand, suitable land, and distance to a major road.

We clustered them three ways with the same algorithm, hierarchical Ward clustering. The only thing that changes between the three is which nodes are allowed to merge.

In variant A, any two nodes can merge. This gives types of node, wherever they are.

In variant B, a node can only merge with its geographic neighbours. This forces each cluster to be one piece on the map.

In variant C, a node can only merge with nodes it is connected to by a transmission line. This is the graph idea from the fifth of November. For the lines we used the open PyPSA-Eur network, which is built from OpenStreetMap.

_146 words, about 65 seconds_

## 7. A constraint turns scattered types into regions

Here are the three results side by side, with five clusters each.

On the left, variant A. The clusters are scattered. The orange squares, for example, appear in the west, in the centre and near Tarragona. These are similar nodes, but they are not a region.

In the middle, variant B. Each cluster is now one piece: the Pyrenees, the Barcelona urban core, the Tarragona industrial area, the western edge, and a large central belt.

On the right, variant C, where the grey lines are the transmission links we used. It mostly agrees with B. The Barcelona and Pyrenees clusters are almost the same. The difference is in the south-west, where C groups Tarragona with the inland nodes it is wired to.

_122 words, about 50 seconds_

## 8. Neighbour clusters are the most stable so far

We measured three things for each variant.

Stability asks: if we take a random eighty percent of the nodes and cluster again, do we get the same groups? One means identical. Variant B scores 0.80, clearly above the other two.

Separation is the silhouette score, which says how tight and distinct the groups are. Here we need to be honest. All three are low, between 0.17 and 0.28. That tells us the nodes form a gradient more than sharply separate groups. So the clusters are a useful way to describe the map. They are not hard boundaries.

The last column counts separate patches on the map. Variant A gives twelve patches for five clusters. B gives exactly five.

So B is our working method today. C is the direction we want, but it scores lowest for now, and the next slides explain why.

_143 words, about 60 seconds_

## 9. Five regions we can describe in plain words

This is what makes the clusters useful. Each row is one of the five regions from variant B. Each column is a feature. Blue means above the average node, orange means below.

Region one is the central belt, 55 nodes, close to average on everything.

Region two is urban Barcelona. Demand is high and there is almost no suitable land. Seven of our top ten nodes for the load-support scenario are here.

Region three is the Pyrenees and the interior. Very low demand and low headroom.

Region four is the western and southern edge, around Ascó and the Lleida side. Lots of operating renewables and land, but little demand. Five of the top ten for renewable absorption are here.

Region five is the Tarragona industrial area, where renewables, pipeline projects, industry and land come together.

So the clusters agree with the baseline ranking, without using any of our weights. The names are ours, and these are similarity groups. We are not claiming they show congestion.

_165 words, about 70 seconds_

## 10. Four limits we know about

We want to be direct about four limits.

First, we have no congestion data. Nothing in the tool today measures congestion or curtailment, so we do not use those words for our results.

Second, the node locations in our dataset are rough. When we matched our nodes to the open transmission network, only 84 of 117 found a line within ten kilometres. The missing ones are mostly substations inside Barcelona and a few that look planned and not yet built. This is the main reason variant C scores lowest. It is a data problem, and we can fix it with better coordinates.

Third, the clusters are soft. They describe a gradient across Catalonia.

Fourth, the baseline scores still use weights we chose ourselves.

We also tried a supervised model that learns from where renewable developers have already built. It works technically, but its label is about renewables, not batteries, so we keep it as supporting evidence only.

_157 words, about 65 seconds_

## 11. Technology first, business case from next week

On the track decision. Until today we put our effort into the technological track, because without real data and a method we can defend, there is no product to build a business on. From next week, the business plan sessions start, and we add the innovation track on top.

Each of us owns one part of the data. Polo owns the grid nodes, and his next task is more precise coordinates, which unlocks the line-based clustering. Fernando owns demand. Hsiang Wei owns congestion, and will either find a usable source or confirm that there is none. Isabella owns renewables and the scoring method. Yuki owns the map layers, the pipeline that joins everything, and the clustering experiment.

Everything runs from one shared repository, so any of us can reproduce the maps from the raw files.

_135 words, about 60 seconds_

## 12. Four weeks, one decision we need from you

Here is the plan for the four weeks we have left.

By the 26th of November, we fix the node coordinates and rerun the line-based clusters. We also make a go or no-go decision on congestion data. If there is no source, we say so and state it as a limitation.

By the 3rd of December, we score nodes inside each region, so a developer sees both the type of region and the best nodes in it. And we validate: do the battery projects that already have permits fall in the regions our map points to?

By the 10th, we freeze the code, write up three case-study sites, and have the business plan drafted.

On the 17th we present the final map, the method and the business case.

We have one question for you. Our line-based clustering uses an approximate open-source network. Is that enough for this project, or do you think we need a real grid model with power flow? Thank you.

_163 words, about 70 seconds_
