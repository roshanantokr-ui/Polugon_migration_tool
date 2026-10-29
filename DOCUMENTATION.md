#User Flows

##User login

-**User enters**:User enters the email and password.
-**Data from FE to BE**:email and password is sent to the backend
-**BE**:Authenticates the req by checking if the user is one of the staffs,
          1. YES - redirects to the problem 
          2. NO - "You do not have staff access" error
-**API**:Authentication is local, no api called.
-**read/write in DB/storage**: 
          1. DB read - user record retrieved and validated through is_staff
          2. DB write - if successful authentication, session is stored in django_session table
-**On complete**: User sees the problem page on successful authentication, on failure, 
they see "You do not have staff access".

##Fetching a problem from Polygon

-**User enters**: Polygon problem id is entered and click button "fetch the problem"
-**Data from FE to BE**: in POST, problem_id is submitted
-**BE**: index() checks problem_id exists,retrieves the prob information and downloafs the problem pkg. Title, statement, i/o format are extracted and 
renders the problem page with the fetched info and test cases.
-**API**: problems/polygon_api.py is the api used to communicate with polygon.
-**Read/write in DB/storage**:
         1. DB read — checks if the problem_id already exists 
         2. DB write — problem record is created or updated with another btn.
         3. Cache — Redis cache stores them for 30 mins.
         4. Cloud storage — the fetch downloads the pkg from polygon to upload in the cloud storage, in this case, google drive.
-**On complete: the page displays the fetched problem details and test-case previews.

##Migrating a problem to the database

-**User enters**: User clicks the Migrate the problem to the database btn after entering the difficulty level,
tags which are optional.
-**Data from FE to BE**: problem_id, migrate_to_db, difficulty, tags, new_tag
-**BE**: Problem details and fetched, problem statement parsed, extract title, statement, i/o format, notes, etc. check for difficulty.
With a check for existing record, if not create a new one, display the success msg.
-**API**: problems/polygon_api.py is the api used to retrieve problem details
-**Read/write in DB/storage**: 
         1. DB read — check existing problem using polygon id and tag information 
         2. DB write — create/update problem record.
-**On complete: success msg

##Migrating test cases to the database

-**User enters**: Clicks migrate test cases to database (problem should already be in the db)
-**Data from FE to BE**: problem_id, migrate_test_cases_to_db
-**BE**: check if the problem has been migrated, if not it terminates. Retrieve test case from redis if cached. extract i/o, sample case status and description.
update/create new test cases and display.
-**API**: problems/polygon_api.py has the class
-**Read/write in DB/storage**:
         1. DB read — problem recors and exisiting test case records 
         2. DB write — create/update ProblemTestCase records
         3. Cache — Redis cache stores them for 30 mins.
         4. Cloud storage — saves test-case information to the database.
-**On complete: success msg

##Uploading test cases to cloud storage

-**User enters**: Clicks migrate test cases to cloud storage.
-**Data from FE to BE**: problem_id, migrate_test_cases_to_db
-**BE**: check if the problem has been migrated, if not it terminates. Retrieve test case from redis if cached. extract i/o, sample case status and description.
update/create new test cases and display.
-**API**: problems/storage/__init__.py
-**Read/write in DB/storage**:
         1. DB read — problem record
         2. Cache — clears Redis cache.
         4. Cloud storage — uploads test case files to test_cases/{problem_id}/ folder
-**On complete: success - displays the number of uploaded test cases and cloud storage path, if upload fails error.