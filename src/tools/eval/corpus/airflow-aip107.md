---
title: "Airflow AIP-107"
space: "DATA"
source_file: "airflow-aip107.html"
---

## Status

<table>
<tbody>
<tr>
<td><strong>State</strong></td>
<td>Draft</td>
</tr>
<tr>
<td><strong>Discussion Thread</strong></td>
<td><p>Initial discussion leading to this AIP:</p>
<ul>
<li>PR: <a href="https://github.com/apache/airflow/pull/63489">https://github.com/apache/airflow/pull/63489</a></li>
<li>Devlist: <a href="https://lists.apache.org/thread/6znvd5rtqnxt5r4hys7qn64j5mflr9g1">https://lists.apache.org/thread/6znvd5rtqnxt5r4hys7qn64j5mflr9g1</a></li>
<li>See also Issue: <a href="https://github.com/apache/airflow/issues/57210">https://github.com/apache/airflow/issues/57210</a></li>
</ul></td>
</tr>
<tr>
<td><strong>Vote Thread</strong></td>
<td><br />
</td>
</tr>
<tr>
<td><strong>Vote Result Thread</strong></td>
<td><br />
</td>
</tr>
<tr>
<td><strong>Progress Tracking (PR/GitHub Project/Issue Label)</strong></td>
<td><br />
</td>
</tr>
<tr>
<td><strong>Date Created</strong></td>
<td><p>2026-04-27</p></td>
</tr>
<tr>
<td><strong>Version Released</strong></td>
<td><br />
</td>
</tr>
<tr>
<td><strong>Authors</strong></td>
<td><p><a href="/confluence/display/~jscheffl">Jens Scheffler</a> </p></td>
</tr>
</tbody>
</table>

## Motivation

**TLDR:** Because of operational problems in processing workload we propose an extension allowing to directly re-queue tasks from triggerer. The [PR \#63489](https://github.com/apache/airflow/pull/63489) raised demand to discuss to ensure awareness for the change is available.

### The details of the Problem

We use Airflow for many workflows of scaled long and large Dags in running 80% KubernetesPodOperator (KPO) workload. To ensure KPO can run scaled and long w/o operation interruptions (worker restart due to re-deployment, Pods with workload sometimes running 4-10h and to be able to scale to thousands of running KPO Pods we need to use and leverage deferred mode excessively.

In KPO with deferred a task is first scheduled to a (Celery in our case) worker which prepares the Pod manifest and starts the Pod. From there it hands-over to triggerer which monitors the Pod running and tails the log so that a user can watch progress. Once the Pod is completed it returns back to a (Celery) worker that finishes-up work, extracts XCom, makes error handling and cleans-up the Pod from K8s. This also means that the Pod is only finished when the XCom is pulled from side-car, the "base" container might be completed and the Pod is only done and deleted when the XCom is collected. Until KPO collects XCom the Pod keeps running.

<img src="/confluence/download/attachments/421957237/Deferring%20Flow.png?version=1&amp;modificationDate=1777325561000&amp;api=v2" id="gliffy-image-421957239-8741" alt="Deferring Flow" />

The current method of scheduling in Airflow is that the Scheduler (*1*) checks all rules of concurrency (`max_active_tasks`, `max_tis_per_dagrun`, `pools`...) in state scheduled before a task is (*2*) queued to be started. (*3*) On the worker when the (*4*) Pod is started it is directly set to "deferred" (*5*) in the database and then *(6)* a triggerer picks-up (no re-scheduling or active distribution to a triggerer, direct DB select) and (*7*) monitors execution. Once Pod is finished *(8)* on the way back today triggerer marks the task "scheduled" which means *(9)* the scheduler logic needs to pick-up the task again for competition. With all other workload that might need to be scheduled in parallel. And re-schedule with all concurrency and priority checks like initially to get to (*10*) queued to be (*11*) re-assigned to a (Celery) worker. Then (*12*) to clean-up the Pod and to read and store XCom the worker uses a (13) the XCom database interface. This implicitly means leaving the state of "deferred" to "scheduled" (*8-10*) the task loses the allocated pool slot and also need to re-allocate a new pool slot.

It most regular situations this is okay. In our scenario it is a problem: We have many Dags competing for the K8s cluster resources and the concurrency features of Airflow joined with priority controls should ensure that important workload runs first. Once there is residual capacity less important batches can consume cluster resources. And with "consume resources" also refers to Pods sitting on the cluster. They free up the cluster space only at point of XCom collected and Pod removed. Before they still consume CPU and ephemeral storage allocations. We limit the amount of workload being able to be sent to K8s by Airflow pools which are the ultimate limit for concurrency on different node pools (e.g. nodes with GPU and nodes w/o GPU). Other workload often runs on Edge workers or directly as Python in Celery.

With multiple Dags and different priorities we had these two effects:

1.  A lower priority batch is running ~N*100 Pods in deferred. A higher priority large batch is started. Pods finishing from the lower priority tasks are assumed to drain the cluster, when they end the task instances are set to "scheduled" and... then stay there until all tasks of the higher priority tasks are worked off (assuming the higher priority tasks are not limited leaving room for the lower priority tasks). So base container of the Pods are completed, the XCom side car waits long - we have seen even 24h - to be XCom collected to be cleaned.
    1.  Additional side effect if pending long the AutoScaler might pick such a node as scaling victim because really idle and after grace period kills the Pod (*between step 7 and 12*) - Later when the workload returns to worker the Pod is showing a HTTP 404 as being gone, XCom is lost... in most cases need to run a retry, else it is anyway a delay and additional hours of re-execution. If no retry just raising failures to users.
    2.  We had the side effect that newer high priority workload was not scheduled by K8s to the (almost idle) Nodes because the previous pending Pods allocated still ephemeral storage and not sufficient space was on K8s nodes for new workload... so the old Pods blocked the new and the higher priority task instances blocked the cleanup of the lower prio instances. A lot of tasks were in a kind of dead-lock.
    3.  As the re-set to state "scheduled" from triggerer also sets the "scheduled" date of the task instance also the from the same "low priority" Dag other pending scheduled task instances are often started earlier. So workers pick-up new tasks to start new Pods but a lot of old Pods are sitting there idle waiting to collect XCom to clean-up
2.  Also sometimes because of operational urgency we use the "enable/disable" scheduling flag on Dags in the UI to administratively turn-off Dag scheduling to leave space for other Dags... or to drain the cluster for some operational procedures e.g. to have a safe ground before maintenance. But as the Dag needs to be (*9*) actively scheduled to process the return from triggerer. If you turn off scheduling the workload in flight is never finishing and is getting stuck like described before. Pods are stale on the cluster, nobody picks-up the XCom. And the problematic scenario is also there is no way to "clean up" such tasks to finish these Dags w/o turning on scheduling... but then also new tasks are queued and you are just not able to drain the cluster. I know we discussed multiple times that we might need a "drain" mode to let existing Dags finish but not scheduling new Dag runs... but such feature is also missing. To say: Scheduling new tasks is tightly coupled with the scheduling of cleanup. Not possible to separate. Getting to the problems as 1 (a-c) as well in the scenario 2.

We thought a while about which options we would have to contribute to improve in general. Assumption and condition is that the initial start on the (Celery) Worker is fast, most time is spent (once) on the triggerer and the return to worker is actually only made for a few seconds to clean-up. And of course we want to minimize latency to (I) free the allocated resources and (II) not to have any additional artificial delay for the user. Which a bit contradicts with the efforts to flip from worker to triggerer and back again.

## Considerations

The following options were considered:

1.  Proposing a new "state" for a task instance, e.g. "re-schedule" that is handled with priority by scheduler. But the scheduler is already a big beast of complexity, adding another loop to handle re-scheduled with all existing complexity might be a large complexity to be added and adding another state in the state model also adds a lot of overhead from documentation to UI...
2.  Finish-up the work on triggerer w/o return to Worker. It is only about cleaning the KPO and... Unfortunately more than just monitoring is very complex to implement and especially XCom DB access is not a desired concept and triggerer does not have support. We also have some specific triaging and error handling automation extended on top of KPO which all in async with the limited capabilities of triggerer would be hard to implement. Main blocker in this view is XCom access.
3.  Dynamically increase priority of a task returning from triggerer. We considered "patching" the priority_weight value of the task instance on the triggerer before return to ensure that tasks returning are just elevated in priority. First we made this from the side via SQL (UPDATE task_instance SET priority_weight=1000 WHERE state='scheduled' AND next_method='trigger_reentry') but actually if the task failed and restarted then it is hard to find and reset the priority back... still a retry would need to be reset down... all feels like a workaround.
4.  Implementing a special mode in Scheduler to select tasks with "next_method" being set as signal they are returning from triggerer in a special way... assuming they have a Pool slot and exclude some of the concurrency checks (As in "scheduled" state the pool slot is actually "lost")\
    But this hard to really propose... as this might be even harder than the first option as well as the today complex code would get even harder in scheduler to consider exceptions in concurrency... with the risk that such special cases exceed the planned concurrency limits if otherwise the pools are exhausted before already.
5.  Adding a REST API that the triggerer can call on scheduler to cross-post workload. That would need to add a new connection and component bundling, a REST API endpoint would need to be added for schedulers to receive these push calls. Probably an alternative but also adds architectural dependability.
6.  **The Solution/PR we propose to discuss here:** If the task skips "scheduled" (*8-10*) state and moves to queue directly the pool slot keeps allocated (assuming that Deferred in actively counting into pool and concurrency limits). Code looked not too complex as just the enqueuing logic from Scheduler could be integrated. In this it is considering that such direct queuing is only possible if the executor supports queues (not working for LocalExecutor!). So the proposed PR made it explicitly opt-in.

### What change do you propose to make?

(Still as of discussion in devlist further discussion on options here in this AIP)

**Option 6)** See [PR \#63489](https://github.com/apache/airflow/pull/63489): A feature to directly enqueue tasks that are finishing from triggerer back to executor queue.

- Pro arguments
  - As of a lot of operational problems recently we tested this and patched this locally into our 3.1.7 triggerer. Works smoothly on production since ~2 months

  - If something goes wrong or Executor is not supported then the existing path setting to "scheduled" is always used as safe fallback

  - It is selective and is an opt-in feature

  - We dramatically reduced latency from Pod completion to cleanup some sometimes 6-24h to a few seconds

  - We assume the cleanup as return from Worker is a small effort only so no harm even if temporarily over-loading some limits

  - ...But frankly speaking the concurrency limits and Pools were checked initially at time of start. Limiting cleanup later on concurrency limits is not adding any benefits but just delays and problems. We just want to finish-up work.

  - But finally actually over-loading is not possible as still the Redis queue is in between - so any free Celery Worker will pick the task. Even in over-load it will just sit in Celery queue for a moment.

  - It is a relatively small change

  - Off-loads scheduler by 50% for all deferred tasks (need to pass scheduler only once)

  - Due to reduced latency on cleanup more "net workload" schedule-able on the cluster, higher cloud utilization / less idle time.
- Contra arguments
  - In Airflow 2 there was a mini-scheduler, there was a hard fight in Airflow 3 to get rid of this!\
    Understand. But we do not want to add a "mini scheduler" we just want to use parts of the Executor code to push the task instance to queue and skip scheduling. It is NOT the target to make any more and schedule anything else.

  - This would skip all concurrency checks and potentially over-load the workers!\
    No. Concurrency rules are checked when the workload is initially started. I know there are parallel bugs we are fighting with to ensure deferred status is counted on all levels into concurrency to correctly keep limits. Assuming that you enable counting deferred into pools, a direct re-queue to worker is just keeping the level of concurrency not adding more workload... just transferring back. And Celery for example has a queue so not really over-loading. It is  mainly intended to clean-up workload which is a low effort task

  - We plan to cut-off components and untangle package dependencies. After worker the Dag parser and triggerer are next. Linking to Executor defeats these plans!\
    Yes, understood. But also today the setting of the task_instance is using direct DB access... and would in such surgery need to be cut to the level that the DB access would need to be moved to execution API back-end. So the cut for re-queueing would move to execution API in future, not triggerer. I think it would be valid to think about the options if such distribution is made how that might evolve in future.

  - This option is risky and we have concerns people have more errors.\
    Feature is opt-in, need to be configured. Per default as proposed in the PR it is not active. Would be also acceptable to mark this experimental for a while.

**Option 2)** (Mainly discussed on Devlist) Add missing features to triggerer environment such that all KPO actions can be finished on the triggerer incl. XCom result push w/o need to re-schedule

- Pro arguments
  - Less problems and no latency
  - No additional coupling and adding executor code to triggerer
- Contra arguments
  - XCom and other interfaces making triggerer a full supervisor-enabled runtime are missing and are a medium to large change. Xcom IO can clog effectiveness for triggerer
  - Custom code inheriting from KPO e.g. for error handling would need to be implemented as triggerer code
  - Would need to be adjusted for any other operator besides KPO - no generic improvement. Note besides KPO no other operator in Airflow codebase known that has this problem.

**Option 1/3)** Tune priority of such tasks in Scheduler to prioritize finishing of work before new tasks start

- Pro arguments
  - No additional coupling and adding executor code to triggerer
- Contra arguments
  - Additional state and scheduling logic in an already very complex scheduling logic
  - Additional state has large consequences in codebase from Enum extension from UI to Plugins and Executors. From a "looking trivial" change to a hairball of complexity

### What problem does it solve?

We (any probably many other Airflow suers as well, see <https://github.com/apache/airflow/issues/57210>) have severe problems in large scale KPO with different priorities that Pods are not properly finishing work. The current setup massively degrades user experience and quality of results.

### Why is it needed?

Ensure Airflow can do robust and scalable KPO (e.g. KubernetesPodOperator) orchestration

### Are there any downsides to this change?

Obviously additional complexity in one or the other way

### Which users are affected by the change?

Depending on solution selected:

- Option 6: Opt-in feature, selectively enabled only
- Option 2: Standard improvement for all KPO users in deferred w/o any action needed
- Option 1/3: Standard improvement for all deferred tasks w/o any action needed

### How are users affected by the change? (e.g. DB upgrade required?)

No DB changes needed in any option.

#### What is the level of migration effort (manual and automated) needed for the users to adapt to the breaking changes? (especially in context of Airflow 3)

No migration effort

### Other considerations?

- Coupling of components is influenced based on the selected option

### What defines this AIP as "done"?

- High volume KPO can be scheduled deferred and do not suffer from other higher priority Dags causing a delay in cleanup. Stability of the scheduling is not suffering from solution.
