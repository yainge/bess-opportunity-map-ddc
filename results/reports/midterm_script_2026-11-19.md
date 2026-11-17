# Mid-term presentation script (19 Nov 2026)

Deck: https://claude.ai/artifact/HWh7VR8j1CZRAYQnRESC8U

Total: 2068 words, about 14 minutes at a steady pace.

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

## 3. Scoring ranks the node. Clustering describes its type.

In October our concept was a ranking. Every substation gets a score, we apply weights, and we sort the list.

After the session on the fifth of November we changed this, but we did not throw the ranking away. We now use two lenses on the same table of nodes.

The first lens is weighted scoring. We first remove land where nothing can be built, such as protected areas, and then a transparent weighted sum over six categories. A high score means the node fits a goal we state openly.

The second lens is clustering. It groups nodes that look alike in the data, and only lets connected or neighbouring nodes merge. A cluster tells you what kind of place a node is. It does not say the node is good.

So the short version is: scoring ranks the node, clustering describes its type. And because clustering does not use our weights, it is a check on the ranking.

_159 words, about 65 seconds_

## 4. Four scenarios make our value judgements visible

This is how the scoring works. Each node gets six category scores: grid access, curtailment, renewables nearby, demand nearby, suitable land, and road access. Each indicator is scaled from zero to one and then weighted and summed. It is a weighted sum, not a black box.

The weights depend on what a battery is for, so we do not hide that choice. We run four scenarios. The baseline balances everything. Renewable absorption puts weight on curtailment and renewables. Connection readiness puts weight on grid access and land. Load support puts weight on demand.

Two rules come first. Protected land, flood zones and dense urban areas are removed from the land we count, so a node cannot score on land where nothing can be built. And these weights are a starting hypothesis, which is why we test how much the ranking depends on them.

_143 words, about 55 seconds_

## 5. All five datasets are now real and in the pipeline

Here is what we have now. All five planned datasets are real and run through the pipeline from raw file to map.

117 transmission nodes, from REE's access-capacity files of the third of November. Fernando matched every node to its real substation on OpenStreetMap, forty of them by hand. Demand for all 947 municipalities. 610 renewable installations, 120 operating. Six map layers for land.

And the fifth dataset, curtailment, is new since last week. REE publishes it only as monthly PDF reports, so we wrote a script that reads the values straight from the charts in each PDF. We now have twelve months, November 2025 to October 2026, checked against the tables in the same reports.

_116 words, about 45 seconds_

## 6. The bottleneck is grid access, not land

This is the most important thing we learned this week, and it came from checking our own data.

Our first node sheet said 98 of 117 nodes had room for storage. When Fernando and Isabella traced it back, that column was only one of REE's three criteria. With the real figure, the minimum over all three, the picture is the opposite. Only ten nodes offer any storage capacity, and only one, Rubió 220, offers it in both directions, which a battery needs because it charges and discharges.

At the same time, 3.4 gigawatts of storage are already granted and two more are pending, across 46 nodes. So developers are not waiting for empty nodes. They apply where the load is and queue.

That changes the question our tool answers. It is less "where is free capacity" and more "where is a battery most useful, and worth queueing for".

_148 words, about 60 seconds_

## 7. The ranking is stable, but it does not yet find where developers go

This is the baseline map with the new data. Green is a better score. The hatched areas are hard constraints such as protected land.

We now score four scenarios, and every node gets a rank. We used to remove any node with a protected area within one kilometre. That removed 38 nodes, including many where developers have asked REE for battery connections. Protected land is already taken out of the suitable land, so removing the whole node counted it twice. We dropped that filter. In the baseline, Albatarrec comes first because it has the most curtailment in Catalonia. Puigpelat and Rubió follow because they are two of the few nodes where REE still shows storage capacity.

The ranking is stable to the weights. We moved every weight up or down by twenty percent, five hundred times, and the baseline top ten almost never changed. It is more sensitive to which indicators we include. Dropping land, for example, changes four of the top ten for connection readiness.

Then we checked the ranking against reality. REE publishes how many megawatts of storage have been granted or requested at each node: 5.3 gigawatts at 46 nodes. Only six of our top twenty nodes have such a request. Random nodes would give about eight. So our weights do not yet reflect what developers actually do. Fixing this is our first task after today.

_229 words, about 90 seconds_

## 8. Same nodes, same features, same method. Only one thing changes: which nodes are allowed to merge.

The second lens is clustering. We took the same 117 nodes and described each with eight features: storage granted or requested at REE, generation granted, operating renewables nearby, renewables in the pipeline, total demand, industrial demand, suitable land, and distance to a major road. We no longer use storage capacity as a feature, because REE shows capacity at only ten nodes.

We clustered them three ways with the same algorithm, hierarchical Ward clustering. The only thing that changes is which nodes are allowed to merge.

In variant A, any two nodes can merge. This gives types of node, wherever they are.

In variant B, a node can only merge with its geographic neighbours, so each cluster is one piece on the map.

In variant C, a node can only merge with nodes it is connected to by a transmission line. Fernando matched OpenStreetMap lines to the REE nodes, which gives us 189 links.

_153 words, about 60 seconds_

## 9. With real node locations, line-based clusters now follow the grid

Here are the three results side by side, with five clusters each.

On the left, variant A. The clusters are scattered across the map. These are similar nodes, but they are not regions.

In the middle, variant B. Each cluster is one piece: the Pyrenees, the Barcelona urban core, the ring of industrial nodes around Barcelona, the western renewable area, and a large central belt.

On the right, variant C, where the grey lines are the links we used. With Fernando's node locations and connections, it now looks much more like the grid. The Pyrenees and the west match variant B. The difference is that C joins the Barcelona core with its ring, and puts the Tarragona and Penedès nodes together as one group.

_124 words, about 50 seconds_

## 10. With Fernando's data, no variant wins on every measure

We measured three things for each variant.

Stability asks: if we take a random eighty percent of the nodes and cluster again, do we get the same groups? All three are now between 0.60 and 0.69, so none is clearly more stable.

Separation is the silhouette score. All three are still low, around 0.2. The nodes form a gradient more than sharp groups, so the clusters describe the map, they are not hard borders.

The last column counts patches on the map. A gives seventeen patches for five clusters. B gives exactly five, and C gives six.

The most important change is in C. With the old coordinates it had the lowest separation. With Fernando's corrected locations and connections, it matches the best variant on separation and stays almost as compact as B. So the line-based idea now works. We keep B as our working map today because it is the easiest to read, and C is close behind.

_159 words, about 65 seconds_

## 11. Developers queue for batteries near Barcelona's industry, not where the renewables are

This is what makes the clusters useful. Each row is one of the five regions from variant B, each column a feature. Blue means above the average node, orange below.

Region one is the central belt: 41 nodes, close to average, with more land and pipeline projects. Half of them have storage requests at REE.

Region two is the Barcelona core: high demand and no land. Only four nodes have requests.

Region three is the industrial ring around Barcelona, in the Vallès and the Baix Llobregat. Seventeen of its twenty-one nodes have storage requests. This is where developers want batteries.

Region four is the west, around Ascó and Lleida, with many renewables, land, and the two curtailment nodes. Only two nodes there have requests.

Region five is the Pyrenees.

So the clusters show something our weighted ranking missed: today, developers ask for battery connections near industrial load, not where renewables are curtailed. The storage requests were not used to build the clusters, which makes this a fair check.

_168 words, about 65 seconds_

## 12. Four limits we know about

We want to be direct about four limits.

First, curtailment. We now have twelve months of REE data by node, and it is small and local in Catalonia: 78 gigawatt hours at two nodes near Lleida, Albatarrec and Mangraners, against more than 5,500 across Spain. It only covers day-ahead limits. So curtailment supports the renewable-absorption scenario at a few nodes, but it is not the main story here.

Second, the line connections come from OpenStreetMap, matched to REE nodes. That is a map of lines, not REE's electrical model. 35 nodes, mostly indoor substations in Barcelona and a few not yet built, have no mapped line, so for them we fall back to nearest neighbours.

Third, the clusters are soft. They describe a gradient across Catalonia.

Fourth, the weights follow our six categories, but we chose the numbers ourselves. They are not yet checked against real battery projects.

We also tried a supervised model that learns from where renewable developers have already built. It works technically, but its label is about renewables, not batteries, so we keep it as supporting evidence only.

_182 words, about 75 seconds_

## 13. Technology first, business case from next week

On the track decision. Until today we put our effort into the technological track, because without real data and a method we can defend, there is no product to build a business on. From next week, the business plan sessions start, and we add the innovation track on top.

Each of us owns one part of the data. Polo owns the grid nodes and access capacity. Fernando owns demand, and he built the matched table of REE nodes with corrected locations and connections, which unlocked the line-based clustering. Hsiang Wei owns congestion and curtailment, from REE's ERNI reports. Isabella owns renewables and the scoring method. Yuki owns the map layers, the pipeline that joins everything, and the clustering experiment.

Everything runs from one shared repository, so any of us can reproduce the maps from the raw files.

_137 words, about 55 seconds_

## 14. Four weeks, one decision we need from you

Here is the plan for the four weeks we have left.

By the 26th of November, we follow up on the validation. We check our scores against the 76 battery sites with permits and against REE's storage requests, and look at which indicators explain where developers go.

By the 3rd of December, we use that check to set the weights, instead of choosing them ourselves. And we score nodes inside each region, so a developer sees both the type of region and the best nodes in it.

By the 10th, we freeze the code, write up three case-study sites, and have the business plan drafted.

On the 17th we present the final map, the method and the business case.

We have one question for you. Our line-based clustering uses OpenStreetMap lines matched to REE nodes. Is that enough for this project, or do you think we need a real grid model with power flow? Thank you.

_156 words, about 60 seconds_
