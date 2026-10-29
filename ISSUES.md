#Product and BE code issues

##I1:
- Problem: slug is created directly with title, which might cause conflict in case of same title between 2 problems
- Impact: product issue as this impairs a user's migration with no way of them knowing it is cause of their naming
- Recommended improvement: add the problem id to the slug or detect collision and add a suffix
- Priority rationale: medium because Valid problems might fail migration because of the conflict

##I2:
- Problem: no timeouts in polygon api requests
- Impact: backend code issue as this is a common miss on having timeout when there are sequential api calls, whcih are dependent.
- Recommended improvement: specify connection and read timeouts for all et http reqs.
- Priority rationale: high priority if migrations are concurrent else mdeium.

##I3:
- Problem: test case data's are checked for additional test cases only only re-migration, not removal of existing test cases
- Impact: i'd classify this under backedn code issue which is also customer facing.
- Recommended improvement: update databse to match latest (add, update, remove the old and removed ones)
- Priority rationale: medium priority as this is a consistency issue only on re migration.


#Edge Case Analysis:

##**A Polygon problem has 0 sample test cases and 15 regular test cases. What happens when you migrate it?**
no new sample records are created, since we dont have an option of checking for stale test cases, if this 0 is after removal, the older cases remain as it is.

##**A problem is migrated with 20 test cases. The problem setter later removes eight on Polygon, leaving 12. What happens when you migrate the same problem again?**
updates the existing ones or creates new ones if there, but does nothin on the removed 8.

##**Two different Polygon problems have the same title, “Two Sum.” You migrate the first successfully, then try to migrate the second. What happens?**
causes creation of same slug, causing collision,  thus causing error on the migration.

##**When you click “Migrate Test Cases to DB,” some data is intentionally discarded. What data is lost, and why could that cause problems?**
trucating after 260 characters, trailing whitespace removal, empty inputs and outputs are removed. This may lead to storing incomplete test data, which are unreliable and not suitable for proper validation.
