def shell(request):
    if not request.user.is_authenticated:
        return {}
    teacher = request.user.profile.role == "teacher"
    courses = (
        request.user.teaching.all()
        if teacher
        else [e.course for e in request.user.enrollments.select_related("course")]
    )
    return {"is_teacher": teacher, "nav_courses": courses}
