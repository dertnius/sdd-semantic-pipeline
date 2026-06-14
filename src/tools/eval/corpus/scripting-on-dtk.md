---
title: "Scripting on DTK"
space: "PLAT"
source_file: "scripting-on-dtk.html"
---

\

DTK is able to execute scripts, this makes it a very powerful tool for the industrialization of processes. DTK interprets its own scripting language.\
\

- **Each line can contain one instruction.**\
  \
- The **SOURCE** and **TARGET** keywords refer to the sandboxes you have selected in the fields in the Retrieve and Deploy windows. There are instructions that are oriented to an environment, if you put SOURCE in the instruction, it will be to the environment that is selected in the Source field.\
  \
- All fields <file_name> or <file> will search in the current workspace. If the file is inside a folder, this field accepts route input: Example: *CustomSettingsMigration\CustomsettingsMigration.csv*\
  \
- If the script is going to be included as Pre Script or Post Script and used in a Deploy from GIT then it can reference the repository root folder with **{gitroot}.** Example: *{gitroot}CustomSettingsMigration\CustomsettingsMigration.csv*\
  \
- Some instrucctions needs keywords along them so they can be identified by DTK this works will be in CAPS. We will name the variables as <variable_name> so you can distinguish them from keywords.\
  \
- Script lines can be commented using "--" and DTK will ignore them

\

\

The available instructions are the following:

## **1. File processing:**

\
**REPLACE:**
------------

The purpose of this instruction is to replace information from column <replace_column> of <replace_file> with information from column <replace_column> of <target_compare_file>, but only when <replace column> of <replace_file> and <source_compare_file> match, and <match_column> of <source_compare_file> and <target_compare_file> match as well.

\

```java
FILE|REPLACE|<replace_file>|<source_compare_file|<target_compare_file>|<replace_column>|<match_column>
```

\

\

> ℹ️ **INFO**: This instruction also accepts multiple <match_column> parameter with "+", for example: FILE\|REPLACE\|<replace_file>\|<source_compare_file\|<target_compare_file>\|<replace_column>\| Id+Name Being that <match_column> a concatenation of those 2 columns.

\

It may seem a little complex, but for that we will give an applied example:

\

*The development team has finished and we want to deploy the improvements we have in the Config environment to the QA environment so that the QA team can test them.*

*The changes are Custom Settings so we need to export the Custom Settings from Config and Import them into QA.*

*We can see that some Custom Settings refer to "Ids" and in Salesforce each environment has its own Ids. For config Custom Settings to work in QA we have to change those Config references to QA references.*

**

<table>
<tbody>
<tr>
<td colspan="4"><p>&lt;replace_file&gt;</p>
<p>CustomSettingsMigration.csv</p>
<p>(Custom Setting extraction from Config)</p></td>
<td><br />
</td>
<td colspan="2"><p>&lt;source_compare_file&gt;</p>
<p>ProfileSource.csv</p>
<p>(Profile Object extraction from CONFIG)</p></td>
<td><br />
</td>
<td colspan="2"><p>&lt;target_compare_file&gt;</p>
<p>ProfileTarget.csv</p>
<p>(Profile Object extraction from QA)</p></td>
</tr>
<tr>
<td>CustomSettingName</td>
<td>ProfileId</td>
<td>Is_Active</td>
<td>Is_Editable</td>
<td><br />
</td>
<td>ProfileName</td>
<td>ProfileId</td>
<td><br />
</td>
<td>ProfileName</td>
<td>ProfileId</td>
</tr>
<tr>
<td>OCE__ActivityHistoryUserObjectSelection__c</td>
<td><strong>a1N0E000000UxlSUAS</strong></td>
<td>Yes</td>
<td>No</td>
<td><br />
</td>
<td><strong>IQVIA_REP</strong></td>
<td><strong>a1N0E000000UxlSUAR</strong></td>
<td><br />
</td>
<td><strong>IQVIA_REP</strong></td>
<td><strong>0051r000007n44xAAA</strong></td>
</tr>
<tr>
<td>OCE__ActivityHistoryUserObjectSelection__c</td>
<td><strong>a1N0E000000UxlSUAR</strong></td>
<td>No</td>
<td>No</td>
<td><br />
</td>
<td><strong>IQVIA_DM</strong></td>
<td><strong>a1N0E000000UxlSUAS</strong></td>
<td><br />
</td>
<td><strong>IQVIA_DM</strong></td>
<td><strong>0051r000007n44xAAB</strong></td>
</tr>
</tbody>
</table>

**

*If we launch this instrucction:*

```java
FILE|REPLACE|CustomSettingsMigration.csv|ProfileSource.csv|ProfileTarget.csv|ProfileId|ProfileName
```

*It will replace those QA Ids in the CustomSettingsMigration file:*

<table>
<tbody>
<tr>
<td colspan="4"><p>&lt;replace_file&gt;</p>
<p>CustomSettingsMigration.csv</p>
<p>(Custom Settings extraction ready to be imported in QA)</p></td>
</tr>
<tr>
<td>CustomSettingName</td>
<td>ProfileId</td>
<td>Is_Active</td>
<td>Is_Editable</td>
</tr>
<tr>
<td>OCE__ActivityHistoryUserObjectSelection__c</td>
<td><strong>0051r000007n44xAAA</strong></td>
<td>Yes</td>
<td>No</td>
</tr>
<tr>
<td>OCE__ActivityHistoryUserObjectSelection__c</td>
<td><strong>0051r000007n44xAAB</strong></td>
<td>No</td>
<td>No</td>
</tr>
</tbody>
</table>

\

*The file is now ready for deploy in the QA environment.*

\

## **COPY:**

The purpose of this instruction is to copy from column <source_column> of <source_compare_file> to column <target_column> of <result_file>, but only when <match_column> of <source_compare_file> and <target_compare_file> match. <result_file> will be an "updated" <target_compare_file> with the copied data from <source_compare_file>

\

```java
FILE|COPY|<result_file>|<source_compare_file>|<target_compare_file>|<source_column>|<target_column>|<match_column>
```

> ℹ️ **INFO**: <result_file> can exist or not , it will be created as a copy of <target_compare_file> with the updated copied values

> ℹ️ **INFO**: This instruction also accepts multiple <match_column> and <source_column> parameter with "+", for example: FILE\|COPY\|<result_file>\|<source_compare_file>\|<target_compare_file>\| Name+Type \|<target_column>\| Id+ProfileId This will copy the contents of Name & Type concatenated into rows where the Id and the ProfileId matches at the same time.

It may seem a little complex, but for that we will give an applied example:

\

*The development want to update the OCE\_\_Product\_\_C object data with external ids in their environment, so the management of data is easier and cross-environments.*

*OCE\_\_UniqueIntegrationId\_\_C is empty and is the field they want to update with some value. They are thinking that it would be nice that this external id is generated based on a concatenation of the Name and the OCE\_\_ProductCode\_\_c*

*They extract with this query a csv file containing Product fields. We will call the csv file*

\

**

```sql
SELECT Id, Name, OCE__ProductCode__c, OCE__UniqueIntegrationId__c FROM OCE__Product__C
```

\

*In this example case <**source_compare_file**> and <**target_compare_file**> will be the same, because we can get all the info we need from the same object.*

**

<table>
<tbody>
<tr>
<td colspan="3"><p>&lt;result_file&gt; </p>
<p><br />
</p>
<p>Product.csv</p>
<p>(can exists, or be created on execution)</p></td>
<td><br />
</td>
<td colspan="4"><p>&lt;source_compare_file&gt;</p>
<p>ProductExtract.csv</p>
<p>(Names extraction from CONFIG)</p></td>
<td><br />
</td>
<td colspan="4"><p>&lt;target_compare_file&gt;</p>
<p>ProductExtract.csv</p>
<p>(Profile Object extraction from QA)</p></td>
</tr>
<tr>
<td>Name</td>
<td>OCE__ProductCode__c</td>
<td>OCE__UniqueIntegrationId__C</td>
<td><br />
</td>
<td>Id &lt;match_field&gt;</td>
<td><p>Name</p>
<p>&lt;source_column&gt;</p></td>
<td><p>OCE__ProductCode__c</p>
<p>&lt;source_column&gt;</p></td>
<td>OCE__UniqueIntegrationId__C</td>
<td><br />
</td>
<td><p>Id</p>
<p>&lt;match_field&gt;</p></td>
<td>Name</td>
<td>OCE__ProductCode__c</td>
<td><p>OCE__UniqueIntegrationId__C</p>
<p>&lt;target_column&gt;<br />
</p></td>
</tr>
<tr>
<td>POLUTIL</td>
<td>P23</td>
<td><br />
</td>
<td><br />
</td>
<td><strong>52342431</strong></td>
<td><strong>POLUTIL</strong></td>
<td><strong>P23</strong></td>
<td><br />
</td>
<td><br />
</td>
<td><strong>52342431</strong></td>
<td>POLUTIL</td>
<td>P23</td>
<td><br />
</td>
</tr>
<tr>
<td>XENOMORPHINE</td>
<td>X17</td>
<td><br />
</td>
<td><br />
</td>
<td><strong>54311234</strong></td>
<td><strong>XENOMORPHINE</strong></td>
<td><strong>X17</strong></td>
<td><br />
</td>
<td><br />
</td>
<td><strong>54311234</strong></td>
<td>XENOMORPHINE</td>
<td>X17</td>
<td><br />
</td>
</tr>
</tbody>
</table>

*If we launch this script line:*

```java
FILE|COPY|Product.csv|ProductExtract.csv|ProductExtract.csv|Name+OCE__ProductCode__c|OCE__UniqueIntegrationID__c|Id
```

**

*The <result_file> after execution appears as:*

<table>
<tbody>
<tr>
<td colspan="3" title="Color de fondo: Verde"><p>&lt;result_file&gt;</p>
<p>Product.csv</p>
<p>(can exists, or be created on execution)</p></td>
</tr>
<tr>
<td title="Color de fondo: Verde">Name</td>
<td title="Color de fondo: Verde">OCE__ProductCode__c</td>
<td title="Color de fondo: Verde">OCE__UniqueIntegrationId__C</td>
</tr>
<tr>
<td title="Color de fondo: Verde">POLUTIL</td>
<td title="Color de fondo: Verde">P23</td>
<td title="Color de fondo: Verde"><strong>POLUTIL_P23</strong></td>
</tr>
<tr>
<td title="Color de fondo: Verde">XENOMORPHINE</td>
<td title="Color de fondo: Verde">X17</td>
<td title="Color de fondo: Verde"><strong>XENOMORPHINE_X17</strong></td>
</tr>
</tbody>
</table>

\

*The file is updated with an external Id now.*

\

## **2. Data Processing:**

****
-----

## **SOQLQUERY:**

The purpose of this instruction is to query a Salesforce environment and copy that data into a csv file.

This queries have to be in Salesforce SOQL language, and it is susceptible to it's limitations. More information can be found here: [SOQL Documentation](https://developer.salesforce.com/docs/atlas.en-us.soql_sosl.meta/soql_sosl/)

\

Format will be delimited by comma, with double quotes when it is necesary.

\

```java
SOURCE/TARGET|SOQLQUERY|<soql_query>|<file_name>
```

\

SOURCE/TARGET will determine the sandbox where the query will be executed.

\

> ℹ️ **INFO**: <soql_query> has to be between double quotes.

\

An example would be the following:

*Dev team wants to extract OCE\_\_Rating\_\_c object to compare it to a file they are maintaining with the correct ratings.*

\

```java
SOURCE|SOQLQUERY|"select, Name, OCE__FieldName__c, OCE__JsonData__c, OCE__JsonMetadata__c, OCE__Label__c, OCE__UniqueIntegrationID__c from OCE__Rating__c"|Rating.csv
```

\

*After executing this scriptline a **Rating.csv** file will be created with this query data from SOURCE environment*

****
-----

## **BULKDELETE:**

ThIs instructions make possible the bulk delete of records in a Salesforce environment.

The file must be a CSV file with only one column: "Id".

```java
SOURCE/TARGET|BULKDELETE|<sobject_name>|<file_name>|<wait_time>
```

<sobject_name> should be filled with the complete sobject name.

<wait_time> let's the user choose the time in minutes that console is going to wait for the process to finish. As the DTK scripting language is going to execute line by line we recommend introducing a time that would last longer than the estimate execution. As soon as the process is finished the console will unlock regardless of the resting waiting time, and will continue with the next execution.

\

Example BULKDELETE csv file:

|                     |
|---------------------|
| Id                  |
| lñkfa091u32okjñlka  |
| lkasjdf01po3kj4ñañ  |
| oaksjd02lsldkfjañlk |
| a09dfjñ1lkdñalksdf  |

An example execution can be:

```java
TARGET|BULKDELETE|OCE__CustomSettingsMigration__c|CustomSettingsToDelete.csv|3
```

****
-----

****
-----

## **BULKUPSERT:**

ThIs instruction make possible the bulk upsert of records in a Salesforce environment.

\

```java
SOURCE/TARGET|BULKUPSERT|<sobject_name>|<file_name>|<id_column>|<wait_time>
```

<sobject_name> should be filled with the complete sobject name.

<id_column> the column name of the external ID.

<wait_time> let's the user choose the time in minutes that console is going to wait for the process to finish. As the DTK scripting language is going to execute line by line we recommend introducing a time that would last longer than the estimate execution. As soon as the process is finished the console will unlock regardless of the resting waiting time, and will continue with the next execution.

\

Example BULKUPSERT csv file:

|                     |        |      |                                 |
|---------------------|--------|------|---------------------------------|
| Id                  | Name   | Type | OCE\_\_UniqueIntegrationId\_\_c |
| lñkfa091u32okjñlka  | Test 1 | A    | TEST1                           |
| lkasjdf01po3kj4ñañ  | Test 2 | B    | TEST2                           |
| oaksjd02lsldkfjañlk | Test 3 | C    | TEST3                           |
| a09dfjñ1lkdñalksdf  | Test 4 | D    | TEST4                           |

An example execution can be:

```java
TARGET|BULKUPSERT|TestObject__c|TestData.csv|OCE__UniqueIntegrationId__c|3
```

\

## **RECORDCREATE / RECORDDELETE / RECORDUPDATE:**

Coming soon. Meanwhile BULKUPSERT & BULKDELETE can be used instead.

****

## **3. Other**

****
-----

## **APEXEXECUTE:**

ThIs instruction make possible the execution of apex code from a local file.

Apex executions will ocur sequencially.

```java
SOURCE/TARGET|APEXEXECUTE|<file>
```

An example execution**:**

```java
TARGET|APEXEXECUTE|{gitroot}apexscript\AccountFilterScript.apex
```

****

## **DEPLOYZIP:**

Coming soon.

\
