from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("classes/new/", views.course_create, name="course_create"),
    path("classes/join/", views.join_course, name="course_join"),
    path("classes/<int:pk>/", views.course_detail, name="course"),
    path("classes/<int:pk>/invitation/", views.course_invitation, name="course_invitation"),
    path("classes/<int:course_id>/exams/new/", views.exam_create, name="exam_create"),
    path("exams/<int:pk>/edit/", views.exam_edit, name="exam_edit"),
    path("exams/<int:pk>/duplicate/", views.exam_duplicate, name="exam_duplicate"),
    path("exams/<int:pk>/publish/", views.exam_publish, name="exam_publish"),
    path("exams/<int:exam_id>/questions/new/", views.question_edit, name="question_create"),
    path("exams/<int:exam_id>/questions/<int:pk>/", views.question_edit, name="question_edit"),
    path("exams/<int:exam_id>/questions/<int:pk>/delete/", views.question_delete, name="question_delete"),
    path("exams/<int:exam_id>/questions/<int:pk>/move/", views.question_move, name="question_move"),
    path("exams/<int:pk>/", views.exam_intro, name="exam_intro"),
    path("exams/<int:pk>/start/", views.exam_start, name="exam_start"),
    path("attempts/<int:pk>/", views.attempt_view, name="attempt"),
    path("attempts/<int:pk>/save/", views.attempt_save, name="attempt_save"),
    path("exams/<int:pk>/gradebook/", views.gradebook, name="gradebook"),
    path("exams/<int:pk>/release/", views.release_results, name="release_results"),
    path("exams/<int:pk>/export/", views.export_grades, name="export_grades"),
    path("review/<int:pk>/", views.review, name="review"),
]
